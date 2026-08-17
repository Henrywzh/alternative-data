"""Leakage-safe walk-forward airline earnings-driver model v2.

The period backtest in :mod:`airline_period_kpi_backtest` is intentionally
kept as the V1 historical calibration.  This module adds a separate research
layer that answers a different question: if the model had only seen earlier
years, what would it have forecast for the next reporting period?

The model is deliberately small and auditable.  It compares:

``flat_ask``
    Prior-period revenue and operating cost scaled by ASK growth.
``flat_rpk``
    Prior-period revenue scaled by RPK growth; cost remains flat-ASK.
``walk_forward_yield_mix``
    RPK-scaled revenue plus a pooled, prior-years-only forecast of total
    revenue per RPK (a yield/mix proxy); cost remains flat-ASK.
``walk_forward_fuel_nonfuel``
    Flat-RPK revenue plus a prior-years-only cost-growth regression that
    decomposes fuel-price and non-fuel/ASK contributions.
``walk_forward_integrated``
    The yield/mix revenue bridge combined with the fuel/non-fuel cost bridge.

This is an operating-profit proxy model (revenue minus operating cost), not a
net-income model.  Historical financial rows from the free discovery layer do
not carry a complete issuer announcement vintage, so the output distinguishes
target-label leakage safety from the stronger, fully-vintage-verified PIT
standard.  EIA fuel observations are safe by observation date but their
historical release vintage is not available in the downloaded public workbook.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR
from .airline_period_kpi_backtest import (
    COMPANY_CODES,
    FINANCIAL_METRICS,
    PERIOD_MONTHS,
    _direct_financial_panel,
    _num,
    _period_label,
)


SOURCE_RECOVERED_MONTHLY_PATH = NORMALIZED_DIR / "airline_operating_kpi_source_recovered.parquet"
PROCESSED_MONTHLY_PATH = Path(__file__).resolve().parents[3] / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
IMPUTED_MONTHLY_PATH = NORMALIZED_DIR / "airline_operating_kpi_imputed.parquet"
FINANCIAL_PATH = NORMALIZED_DIR / "airline_financial_history_trend.csv"
OFFICIAL_DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
ENERGY_PATH = NORMALIZED_DIR / "airline_energy_prices.parquet"

OUTPUT_PATH = NORMALIZED_DIR / "airline_walk_forward_model_v2.csv"
SUMMARY_OUTPUT_PATH = NORMALIZED_DIR / "airline_walk_forward_model_v2_summary.csv"
CURRENT_FORECAST_OUTPUT_PATH = NORMALIZED_DIR / "airline_walk_forward_model_v2_current_forecast.csv"
LOGICAL_OUTPUT_PATH = NORMALIZED_DIR / "airline_walk_forward_model_v2_logical_assumptions.csv"
LOGICAL_SUMMARY_OUTPUT_PATH = NORMALIZED_DIR / "airline_walk_forward_model_v2_logical_assumptions_summary.csv"
MODEL_COMPARISON_OUTPUT_PATH = NORMALIZED_DIR / "airline_walk_forward_model_v2_model_comparison.csv"

MODEL_SPECS = (
    ("flat_ask", "flat_ask", "flat_ask"),
    ("flat_rpk", "flat_rpk", "flat_ask"),
    ("walk_forward_yield_mix", "walk_forward_yield_rpk", "flat_ask"),
    ("walk_forward_fuel_nonfuel", "flat_rpk", "walk_forward_fuel_nonfuel"),
    ("walk_forward_integrated", "walk_forward_yield_rpk", "walk_forward_fuel_nonfuel"),
)

YIELD_FEATURES = (
    "rpk_minus_ask_growth_gap_pp",
    "load_factor_change_pp",
    "prior_yield_growth_pct",
    "period_h2",
    "period_fy",
)
COST_FEATURES = ("ask_growth_pct", "fuel_growth_pct", "period_h2", "period_fy")


def _as_of_date(value: object | None) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp(datetime.now(timezone.utc).date())
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid as_of_date: {value}")
    return pd.Timestamp(parsed).normalize()


def _operating_cutoff(year: int, period: str, *, as_of: pd.Timestamp | None = None) -> pd.Timestamp:
    """Return the pre-result operating-data cutoff for a reporting period.

    H1 uses 15 August as the historical analogue for the current pre-interim
    window.  For the live current-year forecast, the caller passes the actual
    as-of date so data released after the run date cannot enter the forecast.
    H2 and FY use 31 January of the following year, after the observed
    December operating releases in this source set but well before most annual
    financial reports.
    """
    if period == "H1":
        cutoff = pd.Timestamp(f"{year}-08-15")
        return min(cutoff, as_of) if as_of is not None and as_of.year == year else cutoff
    return pd.Timestamp(f"{year + 1}-01-31")


def _period_month_labels(year: int, period: str) -> list[str]:
    return [f"{year}-{month:02d}" for month in PERIOD_MONTHS[period]]


def _period_dates(year: int, period: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    months = PERIOD_MONTHS[period]
    start = pd.Timestamp(f"{year}-{months[0]:02d}-01")
    end = (pd.Timestamp(f"{year}-{months[-1]:02d}-01") + pd.offsets.MonthEnd(1)).normalize()
    return start, end


def _source_value(row: pd.Series) -> tuple[float | None, bool, bool, str]:
    value = _num(row.get("value", row.get("value_raw")))
    if value is None:
        return None, False, False, "missing_numeric_value"
    status = str(row.get("observation_status", "observed"))
    future = str(row.get("uses_future_observation", "False")).lower() in {"true", "1", "yes"}
    announcement = pd.to_datetime(row.get("announcement_date"), errors="coerce")
    release_safe = bool(pd.notna(announcement) and not future)
    if status in {"imputed", "future_interpolated", "logical_assumption"}:
        return value, release_safe and status != "future_interpolated", future, status
    return value, release_safe, future, status


def _select_month_metric(
    frame: pd.DataFrame,
    code: str,
    month: str,
    metric: str,
    cutoff: pd.Timestamp,
    *,
    allow_nearest_assumption: bool,
) -> dict[str, object]:
    """Select a total ASK/RPK observation that was released by ``cutoff``."""
    rows = frame.loc[
        frame["airline_code"].astype(str).str.zfill(6).eq(str(code).zfill(6))
        & frame["month"].astype(str).eq(month)
        & frame["metric"].eq(metric)
    ].copy()
    rows["value_numeric"] = pd.to_numeric(rows.get("value", rows.get("value_raw")), errors="coerce")
    rows = rows.loc[rows["value_numeric"].notna()]
    rows["announcement_date_parsed"] = pd.to_datetime(rows.get("announcement_date"), errors="coerce")
    eligible = rows.loc[rows["announcement_date_parsed"].notna() & rows["announcement_date_parsed"].le(cutoff)]
    method = "observed_total"
    selected: pd.Series | None = None
    if not eligible.empty:
        total = eligible.loc[eligible["region"].astype(str).str.lower().eq("total")]
        if not total.empty:
            selected = total.sort_values("announcement_date_parsed").iloc[-1]
        else:
            regional = eligible.loc[~eligible["region"].astype(str).str.lower().eq("total")]
            if not regional.empty:
                future = regional.get("uses_future_observation", pd.Series(False, index=regional.index)).astype(str).str.lower().isin({"true", "1", "yes"}).any()
                status = "derived_from_imputed_levels" if regional.get("observation_status", pd.Series(dtype=object)).astype(str).eq("imputed").any() else "derived_regional_sum"
                return {
                    "value": float(regional["value_numeric"].sum()),
                    "method": method.replace("total", "regional_sum"),
                    "status": status,
                    "pit_safe": not bool(future),
                    "assumption_used": False,
                    "future_imputation_used": bool(future),
                    "announcement_date": regional["announcement_date_parsed"].max(),
                }
    if selected is None and allow_nearest_assumption and not rows.empty:
        rows["month_distance"] = 0
        selected = rows.sort_values("announcement_date_parsed").iloc[-1]
        method = "logical_assumption_latest_available_for_month"
    if selected is None:
        return {
            "value": None,
            "method": "missing_or_post_cutoff",
            "status": "missing",
            "pit_safe": False,
            "assumption_used": False,
            "future_imputation_used": False,
            "announcement_date": pd.NaT,
        }
    value, release_safe, future, status = _source_value(selected)
    return {
        "value": value,
        "method": method,
        "status": status,
        "pit_safe": bool(release_safe and pd.Timestamp(selected["announcement_date_parsed"]) <= cutoff),
        "assumption_used": method.startswith("logical_assumption"),
        "future_imputation_used": bool(future),
        "announcement_date": selected["announcement_date_parsed"],
    }


def _aggregate_period(
    frame: pd.DataFrame,
    code: str,
    year: int,
    period: str,
    cutoff: pd.Timestamp,
    *,
    allow_nearest_assumption: bool,
) -> dict[str, object]:
    result: dict[str, object] = {
        "company_code": str(code).zfill(6),
        "target_year": year,
        "period": period,
        "statement_period": _period_label(period, year),
        "kpi_cutoff_date": cutoff.strftime("%Y-%m-%d"),
        "kpi_pit_safe": True,
        "kpi_assumption_used": False,
        "kpi_future_imputation_used": False,
        "kpi_latest_announcement_date": pd.NaT,
        "kpi_complete": True,
    }
    latest: list[pd.Timestamp] = []
    for metric in ("ask", "rpk"):
        selected = [
            _select_month_metric(frame, code, month, metric, cutoff, allow_nearest_assumption=allow_nearest_assumption)
            for month in _period_month_labels(year, period)
        ]
        values = [_num(item.get("value")) for item in selected]
        complete = all(value is not None for value in values)
        result[f"{period.lower()}_{metric}_mn"] = float(sum(value for value in values if value is not None)) if complete else None
        result[f"{period.lower()}_{metric}_months_available"] = int(sum(value is not None for value in values))
        result[f"{period.lower()}_{metric}_imputed_months"] = int(sum(str(item.get("status")) in {"imputed", "future_interpolated", "derived_from_imputed_levels"} for item in selected))
        result[f"{period.lower()}_{metric}_logical_assumption_months"] = int(sum(bool(item.get("assumption_used")) for item in selected))
        result["kpi_complete"] = bool(result["kpi_complete"] and complete)
        result["kpi_pit_safe"] = bool(result["kpi_pit_safe"] and complete and all(bool(item.get("pit_safe")) for item in selected))
        result["kpi_assumption_used"] = bool(result["kpi_assumption_used"] or any(bool(item.get("assumption_used")) for item in selected))
        result["kpi_future_imputation_used"] = bool(result["kpi_future_imputation_used"] or any(bool(item.get("future_imputation_used")) for item in selected))
        latest.extend(item["announcement_date"] for item in selected if pd.notna(item.get("announcement_date")))
    ask = _num(result.get(f"{period.lower()}_ask_mn"))
    rpk = _num(result.get(f"{period.lower()}_rpk_mn"))
    result[f"{period.lower()}_load_factor_pct"] = 100.0 * rpk / ask if ask and rpk is not None else None
    result["kpi_pit_safe"] = bool(result["kpi_pit_safe"] and not result["kpi_assumption_used"] and not result["kpi_future_imputation_used"])
    result["kpi_latest_announcement_date"] = max(latest) if latest else pd.NaT
    return result


def _prepare_energy(energy: pd.DataFrame | None) -> pd.DataFrame:
    if energy is None or energy.empty:
        return pd.DataFrame()
    frame = energy.copy()
    frame["observation_date"] = pd.to_datetime(frame.get("observation_date"), errors="coerce")
    frame["value"] = pd.to_numeric(frame.get("value"), errors="coerce")
    frame = frame.loc[frame["observation_date"].notna() & frame["value"].notna()].copy()
    jet = frame.loc[frame["series_id"].astype(str).eq("EER_EPJK_PF4_RGC_DPG")].copy()
    if jet.empty:
        return pd.DataFrame()
    daily = jet.loc[jet.get("frequency", pd.Series(index=jet.index, dtype=object)).astype(str).eq("daily")]
    return daily if not daily.empty else jet


def _fuel_period(energy: pd.DataFrame, year: int, period: str, cutoff: pd.Timestamp) -> dict[str, object]:
    start, end = _period_dates(year, period)
    rows = energy.loc[energy["observation_date"].between(start, min(end, cutoff))].copy() if not energy.empty else pd.DataFrame()
    if rows.empty:
        return {
            "fuel_period_avg_usd_per_gallon": None,
            "fuel_observations": 0,
            "fuel_latest_observation_date": pd.NaT,
            "fuel_source_release_date": None,
            "fuel_pit_status": "missing_fuel_observation",
        }
    release = pd.to_datetime(rows.get("source_release_date"), errors="coerce")
    return {
        "fuel_period_avg_usd_per_gallon": float(rows["value"].mean()),
        "fuel_observations": int(len(rows)),
        "fuel_latest_observation_date": rows["observation_date"].max(),
        "fuel_source_release_date": release.max().strftime("%Y-%m-%d") if release.notna().any() else None,
        "fuel_pit_status": "observation_date_safe_release_vintage_unverified",
    }


def _period_flags(period: str) -> dict[str, float]:
    return {"period_h2": float(period == "H2"), "period_fy": float(period == "FY")}


def _linear_fit(frame: pd.DataFrame, target: str, features: tuple[str, ...]) -> dict[str, object]:
    clean = frame.dropna(subset=[target, *features]).copy()
    clean = clean.loc[np.isfinite(pd.to_numeric(clean[target], errors="coerce"))]
    for feature in features:
        clean = clean.loc[np.isfinite(pd.to_numeric(clean[feature], errors="coerce"))]
    minimum = max(8, len(features) * 2 + 2)
    if len(clean) < minimum:
        median = _num(clean[target].median()) if not clean.empty else 0.0
        return {
            "fitted": False,
            "fallback": True,
            "fallback_reason": "insufficient_prior_year_training_rows",
            "train_rows": int(len(clean)),
            "coefficients": None,
            "feature_names": features,
            "clip_low": _num(clean[target].quantile(0.10)) if not clean.empty else None,
            "clip_high": _num(clean[target].quantile(0.90)) if not clean.empty else None,
            "fallback_value": median if median is not None else 0.0,
        }
    x = clean.loc[:, list(features)].astype(float).to_numpy()
    y = clean[target].astype(float).to_numpy()
    x = np.column_stack([np.ones(len(x)), x])
    # Small ridge stabilization protects the early sparse years without
    # changing the interpretation of the original units.
    xtx = x.T @ x
    penalty = np.eye(xtx.shape[0]) * 1e-6
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(xtx + penalty, x.T @ y)
    return {
        "fitted": True,
        "fallback": False,
        "fallback_reason": None,
        "train_rows": int(len(clean)),
        "coefficients": coefficients,
        "feature_names": features,
        "clip_low": float(np.nanpercentile(y, 5)),
        "clip_high": float(np.nanpercentile(y, 95)),
        "fallback_value": float(np.nanmedian(y)),
    }


def _predict_fit(fit: dict[str, object], row: dict[str, object]) -> tuple[float | None, str, bool]:
    features = tuple(fit["feature_names"])
    if any(_num(row.get(feature)) is None for feature in features):
        return None, "missing_model_feature", True
    if not bool(fit.get("fitted")):
        value = _num(fit.get("fallback_value"))
        return value, str(fit.get("fallback_reason") or "fallback"), True
    coefficients = np.asarray(fit["coefficients"], dtype=float)
    vector = np.asarray([1.0, *[float(row[feature]) for feature in features]], dtype=float)
    raw = float(vector @ coefficients)
    low = _num(fit.get("clip_low"))
    high = _num(fit.get("clip_high"))
    value = float(np.clip(raw, low, high)) if low is not None and high is not None else raw
    return value, "fitted_clipped" if value != raw else "fitted", False


def _base_row(
    company: str,
    year: int,
    period: str,
    *,
    row_status: str,
    assumption_mode: str,
    cutoff: pd.Timestamp,
    prior_fin: dict[str, object] | None,
    target_fin: dict[str, object] | None,
    prior_ops: dict[str, object],
    target_ops: dict[str, object],
    two_prior_fin: dict[str, object] | None,
    two_prior_ops: dict[str, object],
    fuel: dict[str, object],
) -> dict[str, object]:
    suffix = period.lower()
    prior_ask = _num(prior_ops.get(f"{suffix}_ask_mn"))
    target_ask = _num(target_ops.get(f"{suffix}_ask_mn"))
    prior_rpk = _num(prior_ops.get(f"{suffix}_rpk_mn"))
    target_rpk = _num(target_ops.get(f"{suffix}_rpk_mn"))
    prior_lf = _num(prior_ops.get(f"{suffix}_load_factor_pct"))
    target_lf = _num(target_ops.get(f"{suffix}_load_factor_pct"))
    prior_revenue = _num(prior_fin.get("total_revenue")) if prior_fin else None
    target_revenue = _num(target_fin.get("total_revenue")) if target_fin else None
    prior_cost = _num(prior_fin.get("operating_cost")) if prior_fin else None
    target_cost = _num(target_fin.get("operating_cost")) if target_fin else None
    prior_rpk_yield = prior_revenue / prior_rpk if prior_revenue is not None and prior_rpk and prior_rpk > 0 else None
    two_prior_revenue = _num(two_prior_fin.get("total_revenue")) if two_prior_fin else None
    two_prior_rpk = _num(two_prior_ops.get(f"{suffix}_rpk_mn"))
    two_prior_rpk_yield = two_prior_revenue / two_prior_rpk if two_prior_revenue is not None and two_prior_rpk and two_prior_rpk > 0 else None
    prior_yield_growth = 100.0 * prior_rpk_yield / two_prior_rpk_yield - 100.0 if prior_rpk_yield is not None and two_prior_rpk_yield else None
    ask_growth = 100.0 * target_ask / prior_ask - 100.0 if target_ask and prior_ask else None
    rpk_growth = 100.0 * target_rpk / prior_rpk - 100.0 if target_rpk and prior_rpk else None
    target_fuel = _num(fuel.get("fuel_period_avg_usd_per_gallon"))
    # The prior-period fuel average is attached by the caller after this row is
    # built.  Keeping it explicit prevents an accidental target-label lookup.
    row = {
        "dataset_id": "airline_walk_forward_model_v2",
        "company": company,
        "ticker": f"{COMPANY_CODES[company]}.SH",
        "statement_period": _period_label(period, year),
        "period": period,
        "target_year": year,
        "prior_year": year - 1,
        "row_status": row_status,
        "assumption_mode": assumption_mode,
        "model_scope": "walk_forward_target_label_leakage_safe_vintage_limited",
        "forecast_cutoff_date": cutoff.strftime("%Y-%m-%d"),
        "prior_ask_mn": prior_ask,
        "target_ask_mn": target_ask,
        "prior_rpk_mn": prior_rpk,
        "target_rpk_mn": target_rpk,
        "prior_load_factor_pct": prior_lf,
        "target_load_factor_pct": target_lf,
        "ask_growth_pct": ask_growth,
        "rpk_growth_pct": rpk_growth,
        "load_factor_change_pp": target_lf - prior_lf if target_lf is not None and prior_lf is not None else None,
        "rpk_minus_ask_growth_gap_pp": rpk_growth - ask_growth if rpk_growth is not None and ask_growth is not None else None,
        "prior_yield_growth_pct": prior_yield_growth,
        "period_h2": _period_flags(period)["period_h2"],
        "period_fy": _period_flags(period)["period_fy"],
        "prior_revenue_native_mn": prior_revenue,
        "target_revenue_native_mn": target_revenue,
        "prior_operating_cost_native_mn": prior_cost,
        "target_operating_cost_native_mn": target_cost,
        "target_attributable_profit_native_mn": _num(target_fin.get("attributable_net_income")) if target_fin else None,
        "target_operating_profit_proxy_native_mn": target_revenue - target_cost if target_revenue is not None and target_cost is not None else None,
        "prior_financial_source_quality": prior_fin.get("financial_source_quality") if prior_fin else None,
        "target_financial_source_quality": target_fin.get("financial_source_quality") if target_fin else None,
        "prior_financial_pit_status": prior_fin.get("financial_point_in_time_status") if prior_fin else None,
        "target_financial_pit_status": target_fin.get("financial_point_in_time_status") if target_fin else None,
        "prior_financial_announcement_date": prior_fin.get("financial_announcement_date") if prior_fin else None,
        "target_financial_announcement_date": target_fin.get("financial_announcement_date") if target_fin else None,
        "target_actual_used_only_as_evaluation_label": True,
        "kpi_pit_safe": bool(target_ops.get("kpi_pit_safe", False) and prior_ops.get("kpi_pit_safe", False)),
        "kpi_assumption_used": bool(target_ops.get("kpi_assumption_used", False) or prior_ops.get("kpi_assumption_used", False)),
        "kpi_future_imputation_used": bool(target_ops.get("kpi_future_imputation_used", False) or prior_ops.get("kpi_future_imputation_used", False)),
        "kpi_complete": bool(target_ops.get("kpi_complete", False) and prior_ops.get("kpi_complete", False)),
        "target_kpi_latest_announcement_date": target_ops.get("kpi_latest_announcement_date"),
        "target_kpi_cutoff_pass": bool(target_ops.get("kpi_pit_safe", False)),
        "fuel_period_avg_usd_per_gallon": target_fuel,
        "fuel_observations": fuel.get("fuel_observations", 0),
        "fuel_latest_observation_date": fuel.get("fuel_latest_observation_date"),
        "fuel_source_release_date": fuel.get("fuel_source_release_date"),
        "fuel_pit_status": fuel.get("fuel_pit_status"),
        "source_quality": "derived_from_issuer_operating_release_and_free_financial_history",
        "source_note": "Target financial actuals are evaluation labels only. H2 financials are derived FY minus H1; financial discovery history lacks complete historical issuer announcement vintages.",
    }
    return row


def _attach_fuel_growth(row: dict[str, object], prior_fuel: dict[str, object]) -> None:
    current = _num(row.get("fuel_period_avg_usd_per_gallon"))
    prior = _num(prior_fuel.get("fuel_period_avg_usd_per_gallon"))
    row["prior_fuel_period_avg_usd_per_gallon"] = prior
    row["fuel_growth_pct"] = 100.0 * current / prior - 100.0 if current is not None and prior else None
    row["fuel_growth_feature_status"] = "available" if row["fuel_growth_pct"] is not None else "missing_prior_or_target_fuel"


def _attach_predictions(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    base_rows = rows.copy()
    output: list[dict[str, object]] = []
    years = sorted(pd.to_numeric(base_rows["target_year"], errors="coerce").dropna().astype(int).unique())
    for year in years:
        history = base_rows.loc[
            (pd.to_numeric(base_rows["target_year"], errors="coerce") < year)
            & base_rows["row_status"].eq("historical_evaluated")
            & base_rows["kpi_pit_safe"].fillna(False).astype(bool)
        ].copy()
        yield_fit = _linear_fit(history, "revenue_per_rpk_growth_actual_pct", YIELD_FEATURES)
        cost_fit = _linear_fit(history, "operating_cost_growth_actual_pct", COST_FEATURES)
        year_rows = base_rows.loc[pd.to_numeric(base_rows["target_year"], errors="coerce").eq(year)]
        for _, base in year_rows.iterrows():
            shared = base.to_dict()
            yield_pred, yield_status, yield_fallback = _predict_fit(yield_fit, shared)
            cost_pred, cost_status, cost_fallback = _predict_fit(cost_fit, shared)
            # Components are calculated in original percentage-point units.
            if bool(cost_fit.get("fitted")) and not cost_fallback:
                coefficients = np.asarray(cost_fit["coefficients"], dtype=float)
                cost_fuel_component = coefficients[2] * float(shared["fuel_growth_pct"])
                cost_nonfuel_component = coefficients[0] + coefficients[1] * float(shared["ask_growth_pct"]) + coefficients[3] * float(shared["period_h2"]) + coefficients[4] * float(shared["period_fy"])
            else:
                cost_fuel_component = 0.0
                cost_nonfuel_component = _num(shared.get("ask_growth_pct"))
            shared.update(
                {
                    "yield_model_train_rows": int(yield_fit.get("train_rows", 0)),
                    "cost_model_train_rows": int(cost_fit.get("train_rows", 0)),
                    "yield_model_training_max_target_year": int(history["target_year"].max()) if not history.empty else None,
                    "cost_model_training_max_target_year": int(history["target_year"].max()) if not history.empty else None,
                    "yield_model_fallback": bool(yield_fallback),
                    "yield_model_fallback_reason": yield_status,
                    "cost_model_fallback": bool(cost_fallback),
                    "cost_model_fallback_reason": cost_status,
                    "predicted_revenue_per_rpk_growth_pct": yield_pred,
                    "predicted_revenue_per_rpk_growth_raw_or_fallback_pct": yield_pred,
                    "predicted_cost_growth_pct": cost_pred,
                    "predicted_cost_growth_raw_or_fallback_pct": cost_pred,
                    "predicted_fuel_contribution_pct": cost_fuel_component,
                    "predicted_nonfuel_ask_contribution_pct": cost_nonfuel_component,
                }
            )
            prior_revenue = _num(shared.get("prior_revenue_native_mn"))
            prior_cost = _num(shared.get("prior_operating_cost_native_mn"))
            ask_growth = _num(shared.get("ask_growth_pct"))
            rpk_growth = _num(shared.get("rpk_growth_pct"))
            flat_ask_revenue = prior_revenue * (1.0 + ask_growth / 100.0) if prior_revenue is not None and ask_growth is not None else None
            flat_rpk_revenue = prior_revenue * (1.0 + rpk_growth / 100.0) if prior_revenue is not None and rpk_growth is not None else None
            flat_ask_cost = prior_cost * (1.0 + ask_growth / 100.0) if prior_cost is not None and ask_growth is not None else None
            yield_revenue = prior_revenue * (1.0 + rpk_growth / 100.0) * (1.0 + yield_pred / 100.0) if prior_revenue is not None and rpk_growth is not None and yield_pred is not None else None
            fuel_nonfuel_cost = prior_cost * (1.0 + cost_pred / 100.0) if prior_cost is not None and cost_pred is not None else None
            revenue_predictions = {
                "flat_ask": flat_ask_revenue,
                "flat_rpk": flat_rpk_revenue,
                "walk_forward_yield_rpk": yield_revenue,
            }
            cost_predictions = {
                "flat_ask": flat_ask_cost,
                "walk_forward_fuel_nonfuel": fuel_nonfuel_cost,
            }
            for model_name, revenue_model, cost_model in MODEL_SPECS:
                row = shared.copy()
                predicted_revenue = revenue_predictions.get(revenue_model)
                predicted_cost = cost_predictions.get(cost_model)
                actual_revenue = _num(row.get("target_revenue_native_mn"))
                actual_cost = _num(row.get("target_operating_cost_native_mn"))
                actual_op = _num(row.get("target_operating_profit_proxy_native_mn"))
                predicted_op = predicted_revenue - predicted_cost if predicted_revenue is not None and predicted_cost is not None else None
                row.update(
                    {
                        "model_name": model_name,
                        "revenue_model": revenue_model,
                        "cost_model": cost_model,
                        "predicted_revenue_native_mn": predicted_revenue,
                        "predicted_operating_cost_native_mn": predicted_cost,
                        "predicted_operating_profit_proxy_native_mn": predicted_op,
                        "revenue_error_pct": 100.0 * predicted_revenue / actual_revenue - 100.0 if predicted_revenue is not None and actual_revenue else None,
                        "operating_cost_error_pct": 100.0 * predicted_cost / actual_cost - 100.0 if predicted_cost is not None and actual_cost else None,
                        "operating_profit_proxy_error_native_mn": predicted_op - actual_op if predicted_op is not None and actual_op is not None else None,
                        "operating_profit_proxy_error_pct_of_prior_revenue": 100.0 * (predicted_op - actual_op) / abs(prior_revenue) if predicted_op is not None and actual_op is not None and prior_revenue else None,
                        "operating_profit_proxy_direction_correct": bool(np.sign(predicted_op) == np.sign(actual_op)) if predicted_op is not None and actual_op is not None and actual_op != 0 else None,
                        "model_fallback": bool((revenue_model == "walk_forward_yield_rpk" and yield_fallback) or (cost_model == "walk_forward_fuel_nonfuel" and cost_fallback)),
                        "walk_forward_training_max_target_year": int(history["target_year"].max()) if not history.empty else None,
                    }
                )
                output.append(row)
    return pd.DataFrame(output)


def _summary(detail: pd.DataFrame) -> pd.DataFrame:
    evaluated = detail.loc[detail["row_status"].eq("historical_evaluated")].copy()
    if evaluated.empty:
        return pd.DataFrame()
    output: list[dict[str, object]] = []
    for (company, period, model_name), group in evaluated.groupby(["company", "period", "model_name"], sort=True):
        op_direction = group.dropna(subset=["operating_profit_proxy_direction_correct"])
        output.append(
            {
                "dataset_id": "airline_walk_forward_model_v2_summary",
                "company": company,
                "ticker": group["ticker"].iloc[0],
                "period": period,
                "model_name": model_name,
                "historical_evaluated_rows": int(len(group)),
                "historical_year_min": int(group["target_year"].min()),
                "historical_year_max": int(group["target_year"].max()),
                "kpi_pit_safe_rows": int(group["kpi_pit_safe"].fillna(False).astype(bool).sum()),
                "revenue_mae_pct": float(group["revenue_error_pct"].abs().mean()),
                "revenue_bias_pct": float(group["revenue_error_pct"].mean()),
                "operating_cost_mae_pct": float(group["operating_cost_error_pct"].abs().mean()),
                "operating_cost_bias_pct": float(group["operating_cost_error_pct"].mean()),
                "operating_profit_proxy_mae_pct_of_prior_revenue": float(group["operating_profit_proxy_error_pct_of_prior_revenue"].abs().mean()),
                "operating_profit_proxy_direction_accuracy": float(op_direction["operating_profit_proxy_direction_correct"].mean()) if not op_direction.empty else None,
                "yield_model_fallback_rows": int(group["yield_model_fallback"].fillna(False).astype(bool).sum()),
                "cost_model_fallback_rows": int(group["cost_model_fallback"].fillna(False).astype(bool).sum()),
                "source_quality": "walk_forward_target_label_leakage_safe_vintage_limited",
                "source_note": "Training rows have target_year strictly earlier than the forecast row. Financial discovery history lacks complete issuer announcement vintages; fuel observation dates are historical but workbook release vintage is not historical.",
            }
        )
    return pd.DataFrame(output)


def _comparison(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    wide = summary.pivot_table(index=["company", "ticker", "period"], columns="model_name", values=["revenue_mae_pct", "operating_cost_mae_pct", "operating_profit_proxy_mae_pct_of_prior_revenue"], aggfunc="first")
    wide.columns = ["_".join(str(part) for part in col if str(part)) for col in wide.columns]
    wide = wide.reset_index()
    for metric in ("revenue_mae_pct", "operating_cost_mae_pct", "operating_profit_proxy_mae_pct_of_prior_revenue"):
        integrated = f"{metric}_walk_forward_integrated"
        for baseline in ("flat_ask", "flat_rpk", "walk_forward_yield_mix", "walk_forward_fuel_nonfuel"):
            base = f"{metric}_{baseline}"
            if integrated in wide.columns and base in wide.columns:
                wide[f"{metric}_integrated_minus_{baseline}"] = wide[integrated] - wide[base]
    wide["dataset_id"] = "airline_walk_forward_model_v2_model_comparison"
    wide["source_quality"] = "derived_summary_comparison"
    wide["source_note"] = "Negative integrated-minus-baseline MAE means the integrated bridge improved on that historical slice; this is diagnostic and does not select a trade direction by itself."
    return wide


def _load_inputs(
    *,
    monthly: pd.DataFrame | None,
    financial: pd.DataFrame | None,
    official: pd.DataFrame | None,
    energy: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if monthly is None:
        source = SOURCE_RECOVERED_MONTHLY_PATH if SOURCE_RECOVERED_MONTHLY_PATH.exists() else PROCESSED_MONTHLY_PATH
        monthly = pd.read_parquet(source)
    if financial is None:
        financial = pd.read_csv(FINANCIAL_PATH)
    if official is None:
        official = pd.read_csv(OFFICIAL_DRIVERS_PATH)
    if energy is None and ENERGY_PATH.exists():
        energy = pd.read_parquet(ENERGY_PATH)
    frame = monthly.copy()
    frame["month"] = frame["month"].astype(str).str[:7]
    frame["airline_code"] = frame["airline_code"].astype(str).str.zfill(6)
    frame["announcement_date"] = pd.to_datetime(frame.get("announcement_date"), errors="coerce")
    return frame, financial, official, _prepare_energy(energy)


def build_airline_walk_forward_model_v2(
    *,
    monthly: pd.DataFrame | None = None,
    financial: pd.DataFrame | None = None,
    official: pd.DataFrame | None = None,
    energy: pd.DataFrame | None = None,
    assumption_mode: str = "strict_observed",
    as_of_date: object | None = None,
    include_current_forecast: bool = True,
    output_path: Path | None = None,
    summary_output_path: Path | None = None,
    current_forecast_output_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build one V2 layer and return detail, summary and current forecast."""
    if assumption_mode not in {"strict_observed", "logical_assumption"}:
        raise ValueError(f"Unknown assumption_mode: {assumption_mode}")
    as_of = _as_of_date(as_of_date)
    frame, financial, official, energy = _load_inputs(monthly=monthly, financial=financial, official=official, energy=energy)
    financial_map = _direct_financial_panel(financial, official)
    financial_years = sorted(key[1] for key in financial_map)
    max_month_year = int(pd.to_datetime(frame["month"] + "-01").dt.year.max())
    historical_max_year = min(max(financial_years), max_month_year - 1) if financial_years else max_month_year - 1
    current_year = max_month_year
    allow_assumption = assumption_mode == "logical_assumption"

    # Build each year's operating and fuel panel once.  Prior-year rows are
    # known by the target cutoff and are intentionally not re-aggregated with
    # the target year's financial label.
    operating_map: dict[tuple[str, int, str], dict[str, object]] = {}
    fuel_map: dict[tuple[int, str], dict[str, object]] = {}
    for year in range(int(pd.to_datetime(frame["month"] + "-01").dt.year.min()), current_year + 1):
        for period in PERIOD_MONTHS:
            cutoff = _operating_cutoff(year, period)
            fuel_map[(year, period)] = _fuel_period(energy, year, period, cutoff)
            for company, code in COMPANY_CODES.items():
                operating_map[(company, year, period)] = _aggregate_period(
                    frame, code, year, period, cutoff, allow_nearest_assumption=allow_assumption
                )

    base_rows: list[dict[str, object]] = []
    target_years = list(range(2017, historical_max_year + 1))
    if include_current_forecast and current_year > historical_max_year:
        target_years.append(current_year)
    for company in COMPANY_CODES:
        for period in PERIOD_MONTHS:
            for year in target_years:
                is_current = year == current_year and year > historical_max_year
                if is_current and period != "H1":
                    # The active trade horizon is the upcoming interim
                    # result. Do not create pseudo-forecasts for H2/FY when
                    # those operating months have not happened yet.
                    continue
                cutoff = _as_of_date(as_of) if is_current and period == "H1" else _operating_cutoff(year, period)
                # Re-aggregate the live current period at the actual as-of
                # cutoff, rather than the generic historical 15-Aug cutoff.
                target_ops = operating_map.get((company, year, period), {})
                if is_current and period == "H1":
                    target_ops = _aggregate_period(frame, COMPANY_CODES[company], year, period, cutoff, allow_nearest_assumption=False)
                    fuel_map[(year, period)] = _fuel_period(energy, year, period, cutoff)
                prior_ops = operating_map.get((company, year - 1, period), {})
                two_prior_ops = operating_map.get((company, year - 2, period), {})
                prior_fin = financial_map.get((company, year - 1, period))
                target_fin = None if is_current else financial_map.get((company, year, period))
                two_prior_fin = financial_map.get((company, year - 2, period))
                status = "current_forecast" if is_current else "historical_evaluated"
                if not is_current and (prior_fin is None or target_fin is None):
                    status = "insufficient_financial_history"
                if not bool(prior_ops.get("kpi_complete", False)) or not bool(target_ops.get("kpi_complete", False)):
                    status = "current_forecast_insufficient_kpi_coverage" if is_current else "insufficient_kpi_coverage"
                row = _base_row(
                    company,
                    year,
                    period,
                    row_status=status,
                    assumption_mode=assumption_mode,
                    cutoff=cutoff,
                    prior_fin=prior_fin,
                    target_fin=target_fin,
                    prior_ops=prior_ops,
                    target_ops=target_ops,
                    two_prior_fin=two_prior_fin,
                    two_prior_ops=two_prior_ops,
                    fuel=fuel_map.get((year, period), {}),
                )
                _attach_fuel_growth(row, fuel_map.get((year - 1, period), {}))
                # Actual target growth is a label for training/evaluation. It
                # is never passed into the prediction function for that row.
                target_revenue = _num(row.get("target_revenue_native_mn"))
                target_rpk = _num(row.get("target_rpk_mn"))
                prior_revenue = _num(row.get("prior_revenue_native_mn"))
                prior_rpk = _num(row.get("prior_rpk_mn"))
                target_cost = _num(row.get("target_operating_cost_native_mn"))
                prior_cost = _num(row.get("prior_operating_cost_native_mn"))
                row["revenue_per_rpk_growth_actual_pct"] = 100.0 * (target_revenue / target_rpk) / (prior_revenue / prior_rpk) - 100.0 if target_revenue is not None and target_rpk and prior_revenue and prior_rpk else None
                row["operating_cost_growth_actual_pct"] = 100.0 * target_cost / prior_cost - 100.0 if target_cost is not None and prior_cost else None
                row["retrieved_at"] = datetime.now(timezone.utc).isoformat()
                base_rows.append(row)
    base = pd.DataFrame(base_rows)
    detail = _attach_predictions(base)
    summary = _summary(detail)
    current = detail.loc[detail["row_status"].eq("current_forecast")].copy()
    out = output_path or (OUTPUT_PATH if assumption_mode == "strict_observed" else LOGICAL_OUTPUT_PATH)
    summary_out = summary_output_path or (SUMMARY_OUTPUT_PATH if assumption_mode == "strict_observed" else LOGICAL_SUMMARY_OUTPUT_PATH)
    current_out = current_forecast_output_path or CURRENT_FORECAST_OUTPUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    detail.to_csv(out, index=False)
    summary.to_csv(summary_out, index=False)
    if assumption_mode == "strict_observed":
        current.to_csv(current_out, index=False)
    return detail, summary, current


def build_airline_walk_forward_model_v2_comparison(*, as_of_date: object | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build strict V2, logical coverage sensitivity and model comparison."""
    strict, strict_summary, current = build_airline_walk_forward_model_v2(as_of_date=as_of_date)
    if IMPUTED_MONTHLY_PATH.exists():
        logical, logical_summary, _ = build_airline_walk_forward_model_v2(
            monthly=pd.read_parquet(IMPUTED_MONTHLY_PATH),
            assumption_mode="logical_assumption",
            as_of_date=as_of_date,
            include_current_forecast=False,
        )
    else:
        logical, logical_summary = pd.DataFrame(), pd.DataFrame()
    comparison = _comparison(strict_summary)
    comparison["strict_historical_rows"] = int(len(strict.loc[strict["row_status"].eq("historical_evaluated")])) if not strict.empty else 0
    comparison["logical_historical_rows"] = int(len(logical.loc[logical["row_status"].eq("historical_evaluated")])) if not logical.empty else 0
    comparison["logical_summary_rows"] = int(len(logical_summary))
    comparison.to_csv(MODEL_COMPARISON_OUTPUT_PATH, index=False)
    return strict, strict_summary, current, comparison


def fetch_airline_walk_forward_model_v2() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return build_airline_walk_forward_model_v2_comparison()


if __name__ == "__main__":
    detail, summary, current, comparison = fetch_airline_walk_forward_model_v2()
    print(
        f"Built airline walk-forward v2: detail={len(detail)}, summary={len(summary)}, "
        f"current_forecast={len(current)}, comparison={len(comparison)}"
    )
