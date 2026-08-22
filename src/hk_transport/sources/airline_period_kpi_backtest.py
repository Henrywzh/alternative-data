"""H1/H2/FY airline KPI-to-earnings calibration with explicit assumptions.

The existing ``airline_h1_kpi_backtest`` remains the live 1H2026 nowcast.
This module adds a clean historical calibration panel for all three useful
reporting windows:

* H1: January--June reported financials;
* H2: FY less H1, with the arithmetic source quality recorded explicitly;
* FY: January--December reported financials.

The primary layer is strict about monthly operating inputs.  A separate
``logical_flat_nearest_observed`` layer is intentionally available for
coverage sensitivity: when an operating month is absent, it carries the
nearest observed company-total level and marks the result as a logical
assumption.  It is never silently merged into the observed source archive or
treated as a clean point-in-time observation.

Revenue models are deliberately transparent:

``flat_ask``
    prior-period revenue scaled by current ASK growth.
``flat_rpk``
    prior-period revenue scaled by current RPK growth (equivalent to carrying
    forward prior-period revenue per RPK).
``spring_recovery_case``
    a diagnostic sensitivity, not the base forecast.  For Spring only, a
    pronounced capacity-demand recovery signal adds a conservative 10% yield
    premium to the flat-RPK case.  The premium is a pre-declared scenario
    assumption to expose model risk around reopening/mix breaks; it is not
    fitted to the target-period revenue.

This is historical calibration, not a complete executable PIT backtest: the
provider financial history has period-end rows without a full historical
issuer announcement-date vintage.  Monthly KPI dates and assumption lineage
are retained so the limitation remains visible.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR, ROOT_DIR
from ..storage import write_csv_atomic


SOURCE_RECOVERED_MONTHLY_PATH = NORMALIZED_DIR / "airline_operating_kpi_source_recovered.parquet"
IMPUTED_MONTHLY_PATH = NORMALIZED_DIR / "airline_operating_kpi_imputed.parquet"
FINANCIAL_PATH = NORMALIZED_DIR / "airline_financial_history_trend.csv"
OFFICIAL_DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"

OUTPUT_PATH = NORMALIZED_DIR / "airline_period_kpi_backtest.csv"
SUMMARY_OUTPUT_PATH = NORMALIZED_DIR / "airline_period_kpi_backtest_summary.csv"
LOGICAL_OUTPUT_PATH = NORMALIZED_DIR / "airline_period_kpi_backtest_logical_assumptions.csv"
LOGICAL_SUMMARY_OUTPUT_PATH = NORMALIZED_DIR / "airline_period_kpi_backtest_logical_assumptions_summary.csv"
MODEL_COMPARISON_OUTPUT_PATH = NORMALIZED_DIR / "airline_period_kpi_backtest_model_comparison.csv"
SPRING_DIAGNOSTIC_OUTPUT_PATH = NORMALIZED_DIR / "airline_spring_mae_diagnostics.csv"


COMPANY_CODES = {
    "Air China": "601111",
    "China Southern Airlines": "600029",
    "China Eastern Airlines": "600115",
    "Spring Airlines": "601021",
    "Hainan Airlines Holdings": "600221",
    "Juneyao Airlines": "603885",
}

FINANCIAL_METRICS = ("total_revenue", "operating_cost", "attributable_net_income", "fuel_cost")
REQUIRED_FINANCIAL_METRICS = ("total_revenue", "operating_cost", "attributable_net_income")
PERIOD_MONTHS = {
    "H1": tuple(range(1, 7)),
    "H2": tuple(range(7, 13)),
    "FY": tuple(range(1, 13)),
}
PERIOD_LABELS = {"H1": "1H", "H2": "2H", "FY": "FY"}

# A scenario assumption, not a fitted coefficient.  It is deliberately
# conservative versus the actual 2023 Spring rebound and is shown separately
# from the base model so the user can inspect the model-risk range.
SPRING_RECOVERY_YIELD_PREMIUM_PCT = 10.0
SPRING_RECOVERY_RPK_ASK_GAP_THRESHOLD_PP = 15.0
SPRING_RECOVERY_LOAD_FACTOR_THRESHOLD_PP = 10.0


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _period_months(year: int, period: str) -> list[str]:
    return [f"{year}-{month:02d}" for month in PERIOD_MONTHS[period]]


def _period_label(period: str, year: int) -> str:
    return f"{PERIOD_LABELS[period]}{year}"


def _safe_bool(value: object, default: bool = True) -> bool:
    if pd.isna(value):
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _source_row_value(row: pd.Series) -> tuple[float | None, str, bool]:
    value = _num(row.get("value"))
    status = str(row.get("observation_status", "observed"))
    # The source-recovered layer has no imputation columns; its values are
    # official parsed/recovered values and therefore safe for this layer.
    future = _safe_bool(row.get("uses_future_observation", False), default=False)
    if value is None:
        return None, "missing", False
    if status == "imputed":
        return value, "future_interpolated" if future else "imputed", not future
    if status.startswith("derived"):
        return value, status, not future
    return value, status, not future


def _select_month_metric(
    frame: pd.DataFrame,
    code: str,
    month: str,
    metric: str,
    *,
    assumption_mode: str,
) -> dict[str, object]:
    """Select one month/metric and retain its source and assumption status."""
    rows = frame.loc[
        frame["airline_code"].astype(str).str.zfill(6).eq(str(code).zfill(6))
        & frame["month"].astype(str).eq(month)
        & frame["metric"].eq(metric)
    ].copy()
    if rows.empty:
        selected = None
        method = "missing_source_row"
    else:
        rows["value_numeric"] = pd.to_numeric(rows.get("value"), errors="coerce")
        total = rows.loc[
            rows["region"].astype(str).str.lower().eq("total")
            & rows["value_numeric"].notna()
        ]
        selected = total.iloc[0] if not total.empty else None
        method = "observed_total" if selected is not None else "missing_numeric_value"
        if selected is None:
            regional = rows.loc[
                ~rows["region"].astype(str).str.lower().eq("total")
                & rows["value_numeric"].notna()
            ]
            if not regional.empty:
                value = float(regional["value_numeric"].sum())
                statuses = regional.get("observation_status", pd.Series("observed", index=regional.index)).astype(str)
                future = regional.get("uses_future_observation", pd.Series(False, index=regional.index)).map(
                    lambda item: _safe_bool(item, default=False)
                ).any()
                return {
                    "value": value,
                    "method": "observed_regional_sum",
                    "status": "derived_from_imputed_levels" if statuses.eq("imputed").any() else "derived",
                    "pit_safe": not bool(future),
                    "assumption_used": False,
                    "future_imputation_used": bool(future),
                    "announcement_date": pd.to_datetime(regional.get("announcement_date"), errors="coerce").max(),
                }

    if selected is not None:
        value, status, pit_safe = _source_row_value(selected)
        if value is not None:
            return {
                "value": value,
                "method": method,
                "status": status,
                "pit_safe": pit_safe,
                "assumption_used": False,
                "future_imputation_used": status == "future_interpolated",
                "announcement_date": pd.to_datetime(selected.get("announcement_date"), errors="coerce"),
            }

    if assumption_mode != "logical_flat_nearest_observed":
        return {
            "value": None,
            "method": method,
            "status": "missing",
            "pit_safe": False,
            "assumption_used": False,
            "future_imputation_used": False,
            "announcement_date": pd.NaT,
        }

    # Only level metrics are candidates for the logical coverage assumption.
    # The caller never requests a ratio here, so this cannot manufacture a
    # freight/passenger load factor from a missing denominator.
    candidates = frame.loc[
        frame["airline_code"].astype(str).str.zfill(6).eq(str(code).zfill(6))
        & frame["metric"].eq(metric)
    ].copy()
    candidates["value_numeric"] = pd.to_numeric(candidates.get("value"), errors="coerce")
    if "observation_status" in candidates.columns:
        candidates = candidates.loc[~candidates["observation_status"].astype(str).eq("missing")]
    candidates = candidates.loc[candidates["value_numeric"].notna()]
    candidates = candidates.loc[candidates["region"].astype(str).str.lower().eq("total")]
    if candidates.empty:
        return {
            "value": None,
            "method": "logical_assumption_unavailable",
            "status": "missing",
            "pit_safe": False,
            "assumption_used": False,
            "future_imputation_used": False,
            "announcement_date": pd.NaT,
        }
    target_ordinal = pd.Period(month, freq="M").ordinal
    candidate_ordinals = pd.PeriodIndex(candidates["month"].astype(str), freq="M").asi8
    candidates["month_distance"] = (candidate_ordinals - target_ordinal).astype(int)
    candidates["month_distance"] = candidates["month_distance"].abs()
    # Prefer the latest prior observation at equal distance.  That makes the
    # assumption deterministic and avoids accidentally selecting a farther
    # observation because of input row order.
    candidates["is_prior"] = candidates["month"].astype(str) < month
    selected = candidates.sort_values(
        ["month_distance", "is_prior", "month"], ascending=[True, False, False]
    ).iloc[0]
    return {
        "value": float(selected["value_numeric"]),
        "method": "logical_assumption_flat_nearest_observed",
        "status": "logical_assumption",
        "pit_safe": False,
        "assumption_used": True,
        "future_imputation_used": False,
        "announcement_date": pd.to_datetime(selected.get("announcement_date"), errors="coerce"),
        "assumption_source_month": str(selected.get("month")),
        "assumption_gap_months": int(selected.get("month_distance")),
    }


def _aggregate_period(
    frame: pd.DataFrame,
    code: str,
    year: int,
    period: str,
    *,
    assumption_mode: str,
) -> dict[str, object]:
    months = _period_months(year, period)
    result: dict[str, object] = {
        "company_code": str(code).zfill(6),
        "target_year": year,
        "period": period,
        "statement_period": _period_label(period, year),
        "expected_months": len(months),
        "months_available": 0,
        "kpi_imputation_months": 0,
        "kpi_future_imputation_months": 0,
        "kpi_logical_assumption_months": 0,
        "kpi_pit_safe": True,
        "kpi_assumption_used": False,
        "kpi_latest_announcement_date": pd.NaT,
    }
    latest_dates: list[pd.Timestamp] = []
    complete = True
    for metric in ("ask", "rpk"):
        selected: list[dict[str, object]] = [
            _select_month_metric(frame, code, month, metric, assumption_mode=assumption_mode)
            for month in months
        ]
        values = [_num(item.get("value")) for item in selected]
        complete = complete and all(value is not None for value in values)
        result[f"{period.lower()}_{metric}_mn"] = float(sum(value for value in values if value is not None)) if complete else None
        result[f"{period.lower()}_{metric}_months_available"] = int(sum(value is not None for value in values))
        result[f"{period.lower()}_{metric}_imputed_months"] = int(
            sum(str(item.get("status")) in {"imputed", "future_interpolated", "derived_from_imputed_levels"} for item in selected)
        )
        result[f"{period.lower()}_{metric}_future_imputation_months"] = int(
            sum(bool(item.get("future_imputation_used")) for item in selected)
        )
        result[f"{period.lower()}_{metric}_logical_assumption_months"] = int(
            sum(bool(item.get("assumption_used")) for item in selected)
        )
        result["kpi_imputation_months"] += result[f"{period.lower()}_{metric}_imputed_months"]
        result["kpi_future_imputation_months"] += result[f"{period.lower()}_{metric}_future_imputation_months"]
        result["kpi_logical_assumption_months"] += result[f"{period.lower()}_{metric}_logical_assumption_months"]
        result["kpi_assumption_used"] = bool(result["kpi_assumption_used"] or any(item.get("assumption_used") for item in selected))
        result["kpi_pit_safe"] = bool(result["kpi_pit_safe"] and all(bool(item.get("pit_safe")) for item in selected))
        latest_dates.extend(
            [item["announcement_date"] for item in selected if not pd.isna(item.get("announcement_date"))]
        )
        if not complete:
            # Do not let an incomplete ASK/RPK series turn into a partial sum.
            # Revenue scaling needs the full reporting window.
            break
    result["kpi_complete"] = bool(complete)
    result["kpi_pit_safe"] = bool(result["kpi_pit_safe"] and complete and not result["kpi_assumption_used"])
    ask = _num(result.get(f"{period.lower()}_ask_mn"))
    rpk = _num(result.get(f"{period.lower()}_rpk_mn"))
    result[f"{period.lower()}_load_factor_pct"] = 100.0 * rpk / ask if ask and rpk is not None else None
    result["kpi_latest_announcement_date"] = max(latest_dates) if latest_dates else pd.NaT
    return result


def _direct_financial_panel(financial: pd.DataFrame, official: pd.DataFrame) -> dict[tuple[str, int, str], dict[str, object]]:
    """Build direct H1/FY rows and derived H2 rows in native currency."""
    result: dict[tuple[str, int, str], dict[str, object]] = {}
    provider = financial.copy()
    provider["statement_period"] = provider["statement_period"].astype(str)
    provider["period_type"] = provider["period_type"].astype(str)
    provider["year"] = pd.to_numeric(provider["statement_period"].str[:4], errors="coerce")
    provider["period"] = np.where(
        provider["period_type"].eq("FY") | provider["statement_period"].str.endswith("-12"), "FY",
        np.where(provider["period_type"].eq("H1_or_2Q") | provider["statement_period"].str.endswith("-06"), "H1", None),
    )
    provider = provider.loc[provider["period"].isin(["H1", "FY"]) & provider["metric"].isin(FINANCIAL_METRICS)].copy()
    for (company, year, period), group in provider.groupby(["company", "year", "period"], sort=True):
        if pd.isna(year):
            continue
        row: dict[str, object] = {
            "company": str(company),
            "year": int(year),
            "period": str(period),
            "financial_source_quality": "akshare_discovery_historical",
            "financial_point_in_time_status": "period_end_only_no_announcement_date",
            "financial_announcement_date": None,
            "financial_source_path": str(FINANCIAL_PATH),
            "financial_source_url": None,
        }
        for metric in FINANCIAL_METRICS:
            values = pd.to_numeric(group.loc[group["metric"].eq(metric), "value_native"], errors="coerce").dropna()
            row[metric] = float(values.iloc[0]) if not values.empty else None
        result[(str(company), int(year), str(period))] = row

    if not official.empty:
        official = official.copy()
        official["statement_period"] = official["statement_period"].astype(str)
        official["year"] = pd.to_numeric(official["statement_period"].str.extract(r"(\d{4})")[0], errors="coerce")
        official["period"] = np.where(official["statement_period"].str.startswith("1H"), "H1", np.where(official["statement_period"].str.startswith("FY"), "FY", None))
        official = official.loc[official["period"].isin(["H1", "FY"]) & official["metric"].isin((*FINANCIAL_METRICS, "profit_total"))].copy()
        for (company, year, period), group in official.groupby(["company", "year", "period"], sort=True):
            if pd.isna(year):
                continue
            key = (str(company), int(year), str(period))
            row = result.setdefault(
                key,
                {
                    "company": str(company), "year": int(year), "period": str(period),
                    "financial_source_quality": "primary_issuer",
                    "financial_point_in_time_status": "issuer_announcement_date_available",
                    "financial_announcement_date": None,
                    "financial_source_path": str(OFFICIAL_DRIVERS_PATH),
                    "financial_source_url": None,
                },
            )
            for metric in FINANCIAL_METRICS:
                selected = group.loc[group["metric"].eq(metric), "value_native"]
                if metric == "attributable_net_income" and selected.empty:
                    selected = group.loc[group["metric"].eq("profit_total"), "value_native"]
                    if not selected.empty:
                        row["financial_profit_metric"] = "profit_total_fallback"
                values = pd.to_numeric(selected, errors="coerce").dropna()
                if not values.empty:
                    row[metric] = float(values.iloc[0])
            announced = pd.to_datetime(group.get("announced_at"), errors="coerce").dropna()
            if not announced.empty:
                row["financial_announcement_date"] = announced.iloc[0].strftime("%Y-%m-%d")
            urls = group.get("source_url", pd.Series(dtype=object)).dropna().astype(str)
            if not urls.empty:
                row["financial_source_url"] = urls.iloc[0]
            row["financial_source_quality"] = "primary_issuer"
            row["financial_point_in_time_status"] = "issuer_announcement_date_available"
            row["financial_source_path"] = str(OFFICIAL_DRIVERS_PATH)

    companies = sorted({key[0] for key in result})
    years = sorted({key[1] for key in result})
    for company in companies:
        for year in years:
            h1 = result.get((company, year, "H1"))
            fy = result.get((company, year, "FY"))
            if not h1 or not fy:
                continue
            row: dict[str, object] = {
                "company": company,
                "year": year,
                "period": "H2",
                "financial_source_quality": "derived_fy_minus_h1",
                "financial_point_in_time_status": "derived_from_period_end_rows",
                "financial_announcement_date": fy.get("financial_announcement_date"),
                "financial_source_path": f"{fy.get('financial_source_path')};{h1.get('financial_source_path')}",
                "financial_source_url": ";".join(str(value) for value in [fy.get("financial_source_url"), h1.get("financial_source_url")] if value),
            }
            for metric in FINANCIAL_METRICS:
                fy_value = _num(fy.get(metric))
                h1_value = _num(h1.get(metric))
                row[metric] = fy_value - h1_value if fy_value is not None and h1_value is not None else None
            result[(company, year, "H2")] = row
    return result


def _row_base(company: str, year: int, period: str, status: str, assumption_mode: str) -> dict[str, object]:
    return {
        "dataset_id": "airline_period_kpi_backtest",
        "company": company,
        "ticker": f"{COMPANY_CODES[company]}.SH",
        "statement_period": _period_label(period, year),
        "period": period,
        "target_year": year,
        "prior_year": year - 1,
        "row_status": status,
        "kpi_assumption_mode": assumption_mode,
        "model_scope": "historical_calibration_not_strict_pit_backtest",
        "source_quality": "derived_historical_calibration",
        "source_note": (
            "H2 financials are derived as FY minus H1. Historical financial rows are period-end history without a complete issuer announcement-date vintage; monthly KPI lineage and logical assumptions are retained for audit. The residual-profit diagnostic carries prior attributable profit minus prior operating contribution and is not a granular finance/tax waterfall."
        ),
    }


def _attach_period_prediction(
    row: dict[str, object],
    prior_fin: dict[str, object],
    current_fin: dict[str, object] | None,
    prior_ops: dict[str, object],
    current_ops: dict[str, object],
) -> None:
    period = str(row["period"]).lower()
    prev_ask = _num(prior_ops.get(f"{period}_ask_mn"))
    cur_ask = _num(current_ops.get(f"{period}_ask_mn"))
    prev_rpk = _num(prior_ops.get(f"{period}_rpk_mn"))
    cur_rpk = _num(current_ops.get(f"{period}_rpk_mn"))
    prev_lf = _num(prior_ops.get(f"{period}_load_factor_pct"))
    cur_lf = _num(current_ops.get(f"{period}_load_factor_pct"))
    row[f"prior_{period}_ask_mn"] = prev_ask
    row[f"current_{period}_ask_mn"] = cur_ask
    row[f"prior_{period}_rpk_mn"] = prev_rpk
    row[f"current_{period}_rpk_mn"] = cur_rpk
    row[f"prior_{period}_load_factor_pct"] = prev_lf
    row[f"current_{period}_load_factor_pct"] = cur_lf
    row["ask_growth_pct"] = 100.0 * cur_ask / prev_ask - 100.0 if cur_ask and prev_ask else None
    row["rpk_growth_pct"] = 100.0 * cur_rpk / prev_rpk - 100.0 if cur_rpk and prev_rpk else None
    row["load_factor_change_pp"] = cur_lf - prev_lf if cur_lf is not None and prev_lf is not None else None
    row["rpk_minus_ask_growth_gap_pp"] = row["rpk_growth_pct"] - row["ask_growth_pct"] if row["rpk_growth_pct"] is not None and row["ask_growth_pct"] is not None else None
    row["prior_kpi_pit_safe"] = bool(prior_ops.get("kpi_pit_safe", False))
    row["current_kpi_pit_safe"] = bool(current_ops.get("kpi_pit_safe", False))
    row["kpi_pit_safe"] = bool(row["prior_kpi_pit_safe"] and row["current_kpi_pit_safe"])
    row["prior_kpi_assumption_used"] = bool(prior_ops.get("kpi_assumption_used", False))
    row["current_kpi_assumption_used"] = bool(current_ops.get("kpi_assumption_used", False))
    row["kpi_assumption_used"] = bool(row["prior_kpi_assumption_used"] or row["current_kpi_assumption_used"])
    row["kpi_future_imputation_used"] = bool(
        prior_ops.get("kpi_future_imputation_months", 0) or current_ops.get("kpi_future_imputation_months", 0)
    )
    row["kpi_logical_assumption_months"] = int(
        prior_ops.get("kpi_logical_assumption_months", 0) or 0
    ) + int(current_ops.get("kpi_logical_assumption_months", 0) or 0)
    row["kpi_latest_announcement_date"] = current_ops.get("kpi_latest_announcement_date")
    row["kpi_pre_report_cutoff_pass"] = True

    prev_revenue = _num(prior_fin.get("total_revenue"))
    prev_cost = _num(prior_fin.get("operating_cost"))
    prev_profit = _num(prior_fin.get("attributable_net_income"))
    current_revenue = _num(current_fin.get("total_revenue")) if current_fin else None
    current_cost = _num(current_fin.get("operating_cost")) if current_fin else None
    current_profit = _num(current_fin.get("attributable_net_income")) if current_fin else None
    ask_factor = 1.0 + row["ask_growth_pct"] / 100.0 if row["ask_growth_pct"] is not None else None
    rpk_factor = 1.0 + row["rpk_growth_pct"] / 100.0 if row["rpk_growth_pct"] is not None else None
    row["prior_revenue_native_mn"] = prev_revenue
    row["prior_operating_cost_native_mn"] = prev_cost
    row["prior_attributable_profit_native_mn"] = prev_profit
    row["target_revenue_native_mn"] = current_revenue
    row["target_operating_cost_native_mn"] = current_cost
    row["target_attributable_profit_native_mn"] = current_profit
    row["flat_ask_revenue_pred_native_mn"] = prev_revenue * ask_factor if prev_revenue is not None and ask_factor is not None else None
    row["flat_rpk_revenue_pred_native_mn"] = prev_revenue * rpk_factor if prev_revenue is not None and rpk_factor is not None else None
    row["flat_ask_cost_pred_native_mn"] = prev_cost * ask_factor if prev_cost is not None and ask_factor is not None else None
    prior_operating_contribution = (
        prev_revenue - prev_cost
        if prev_revenue is not None and prev_cost is not None
        else None
    )
    prior_below_operating_residual = (
        prev_profit - prior_operating_contribution
        if prev_profit is not None and prior_operating_contribution is not None
        else None
    )
    flat_ask_operating_contribution = (
        row["flat_ask_revenue_pred_native_mn"] - row["flat_ask_cost_pred_native_mn"]
        if row["flat_ask_revenue_pred_native_mn"] is not None
        and row["flat_ask_cost_pred_native_mn"] is not None
        else None
    )
    row["prior_operating_contribution_native_mn"] = prior_operating_contribution
    row["prior_attributable_below_operating_residual_native_mn"] = prior_below_operating_residual
    row["flat_ask_profit_residual_pred_native_mn"] = (
        flat_ask_operating_contribution + prior_below_operating_residual
        if flat_ask_operating_contribution is not None
        and prior_below_operating_residual is not None
        else None
    )
    row["flat_ask_profit_residual_pred_status"] = (
        "prior_attributable_below_operating_residual"
        if prior_below_operating_residual is not None
        else "unavailable_missing_prior_revenue_cost_or_profit"
    )

    # Spring's high MAE is concentrated in the post-reopening mix break.  The
    # recovery case is an explicit sensitivity around that risk, not a hidden
    # replacement for flat-RPK and not a target-fitted forecast.
    recovery_signal = bool(
        row["company"] == "Spring Airlines"
        and row["rpk_minus_ask_growth_gap_pp"] is not None
        and row["load_factor_change_pp"] is not None
        and row["rpk_minus_ask_growth_gap_pp"] >= SPRING_RECOVERY_RPK_ASK_GAP_THRESHOLD_PP
        and row["load_factor_change_pp"] >= SPRING_RECOVERY_LOAD_FACTOR_THRESHOLD_PP
    )
    row["spring_recovery_signal"] = recovery_signal
    row["spring_recovery_yield_premium_pct"] = SPRING_RECOVERY_YIELD_PREMIUM_PCT if recovery_signal else 0.0
    flat_rpk = _num(row.get("flat_rpk_revenue_pred_native_mn"))
    row["spring_recovery_case_revenue_pred_native_mn"] = (
        flat_rpk * (1.0 + SPRING_RECOVERY_YIELD_PREMIUM_PCT / 100.0)
        if flat_rpk is not None and recovery_signal else flat_rpk
    )
    row["revenue_per_rpk_actual_growth_pct"] = (
        100.0 * (current_revenue / cur_rpk) / (prev_revenue / prev_rpk) - 100.0
        if current_revenue is not None and prev_revenue is not None and cur_rpk and prev_rpk and prev_revenue and current_revenue else None
    )
    row["revenue_per_ask_actual_growth_pct"] = (
        100.0 * (current_revenue / cur_ask) / (prev_revenue / prev_ask) - 100.0
        if current_revenue is not None and prev_revenue is not None and cur_ask and prev_ask and prev_revenue and current_revenue else None
    )
    row["cost_per_ask_actual_growth_pct"] = (
        100.0 * (current_cost / cur_ask) / (prev_cost / prev_ask) - 100.0
        if current_cost is not None and prev_cost is not None and cur_ask and prev_ask and prev_cost and current_cost else None
    )
    row["target_financial_source_quality"] = current_fin.get("financial_source_quality") if current_fin else None
    row["target_financial_pit_status"] = current_fin.get("financial_point_in_time_status") if current_fin else None
    row["target_financial_announcement_date"] = current_fin.get("financial_announcement_date") if current_fin else None
    row["prior_financial_source_quality"] = prior_fin.get("financial_source_quality")
    row["prior_financial_pit_status"] = prior_fin.get("financial_point_in_time_status")
    if current_fin is None:
        return
    error_fields = {
        "flat_ask_revenue_pred_native_mn": "revenue_error_flat_ask_pct",
        "flat_rpk_revenue_pred_native_mn": "revenue_error_flat_rpk_pct",
        "spring_recovery_case_revenue_pred_native_mn": "revenue_error_spring_recovery_case_pct",
        "flat_ask_cost_pred_native_mn": "operating_cost_error_flat_ask_pct",
    }
    for prediction, error_name in error_fields.items():
        actual = current_cost if prediction == "flat_ask_cost_pred_native_mn" else current_revenue
        predicted = _num(row.get(prediction))
        row[error_name] = 100.0 * predicted / actual - 100.0 if predicted is not None and actual else None
    row["profit_direction_correct_flat_ask"] = None
    row["profit_direction_correct_flat_ask_residual"] = None
    row["profit_error_flat_ask_residual_native_mn"] = None
    row["profit_abs_error_flat_ask_residual_native_mn"] = None
    flat_cost = _num(row.get("flat_ask_cost_pred_native_mn"))
    flat_revenue = _num(row.get("flat_ask_revenue_pred_native_mn"))
    if flat_revenue is not None and flat_cost is not None and current_profit is not None:
        row["profit_direction_correct_flat_ask"] = bool(np.sign(flat_revenue - flat_cost) == np.sign(current_profit))
    residual_pred = _num(row.get("flat_ask_profit_residual_pred_native_mn"))
    if residual_pred is not None and current_profit is not None:
        row["profit_error_flat_ask_residual_native_mn"] = residual_pred - current_profit
        row["profit_abs_error_flat_ask_residual_native_mn"] = abs(residual_pred - current_profit)
        row["profit_direction_correct_flat_ask_residual"] = bool(
            np.sign(residual_pred) == np.sign(current_profit)
        )


def _summary(rows: pd.DataFrame) -> pd.DataFrame:
    historical = rows.loc[rows["row_status"].eq("historical_evaluated")].copy()
    output: list[dict[str, object]] = []
    for (company, period), group in historical.groupby(["company", "period"], sort=True):
        profit_valid = group.dropna(subset=["profit_direction_correct_flat_ask"])
        residual_profit_valid = group.dropna(subset=["profit_direction_correct_flat_ask_residual"])
        residual_profit_error = group["profit_abs_error_flat_ask_residual_native_mn"].dropna()
        output.append(
            {
                "dataset_id": "airline_period_kpi_backtest_summary",
                "company": company,
                "ticker": f"{COMPANY_CODES[company]}.SH",
                "period": period,
                "historical_evaluated_rows": int(len(group)),
                "historical_year_min": int(group["target_year"].min()),
                "historical_year_max": int(group["target_year"].max()),
                "pit_safe_evaluated_rows": int(group["kpi_pit_safe"].fillna(False).astype(bool).sum()),
                "logical_assumption_rows": int(group["kpi_assumption_used"].fillna(False).astype(bool).sum()),
                "future_imputation_rows": int(group["kpi_future_imputation_used"].fillna(False).astype(bool).sum()),
                "revenue_flat_ask_mae_pct": float(group["revenue_error_flat_ask_pct"].abs().mean()),
                "revenue_flat_rpk_mae_pct": float(group["revenue_error_flat_rpk_pct"].abs().mean()),
                "revenue_spring_recovery_case_mae_pct": float(group["revenue_error_spring_recovery_case_pct"].abs().mean()),
                "operating_cost_flat_ask_mae_pct": float(group["operating_cost_error_flat_ask_pct"].abs().mean()),
                "profit_direction_valid_rows": int(len(profit_valid)),
                "profit_direction_accuracy": float(profit_valid["profit_direction_correct_flat_ask"].mean()) if not profit_valid.empty else None,
                "residual_profit_direction_valid_rows": int(len(residual_profit_valid)),
                "residual_profit_direction_accuracy": float(residual_profit_valid["profit_direction_correct_flat_ask_residual"].mean()) if not residual_profit_valid.empty else None,
                "residual_profit_mae_native_mn": float(residual_profit_error.mean()) if not residual_profit_error.empty else None,
                "source_quality": "historical_calibration_not_strict_pit_backtest",
                "source_note": "H2 is FY minus H1. The residual-profit model carries prior attributable profit minus prior operating contribution as a transparent below-operating bridge; logical-assumption rows are coverage sensitivity only and are not silently promoted to observed data.",
            }
        )
    return pd.DataFrame(output)


def _spring_diagnostics(rows: pd.DataFrame) -> pd.DataFrame:
    spring = rows.loc[
        rows["company"].eq("Spring Airlines") & rows["row_status"].eq("historical_evaluated")
    ].copy()
    if spring.empty:
        return pd.DataFrame()
    spring["regime"] = np.select(
        [
            spring["target_year"].le(2019),
            spring["target_year"].between(2020, 2022),
            spring["spring_recovery_signal"].fillna(False),
        ],
        ["pre_covid", "covid_disruption_or_restriction", "post_reopening_recovery"],
        default="post_recovery_normalization",
    )
    return spring[
        [
            "statement_period", "period", "target_year", "regime", "ask_growth_pct", "rpk_growth_pct",
            "rpk_minus_ask_growth_gap_pp", "load_factor_change_pp", "revenue_per_rpk_actual_growth_pct",
            "revenue_error_flat_ask_pct", "revenue_error_flat_rpk_pct",
            "revenue_error_spring_recovery_case_pct", "kpi_assumption_used", "kpi_pit_safe",
        ]
    ].sort_values(["period", "target_year"])


def build_airline_period_kpi_backtest(
    *,
    monthly: pd.DataFrame | None = None,
    financial: pd.DataFrame | None = None,
    official: pd.DataFrame | None = None,
    assumption_mode: str = "strict_observed",
    retrieved_at: str | None = None,
    output_path: Path | None = None,
    summary_output_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build H1/H2/FY historical calibration for one input/assumption layer."""
    if assumption_mode not in {"strict_observed", "logical_flat_nearest_observed"}:
        raise ValueError(f"Unknown assumption_mode: {assumption_mode}")
    if monthly is None:
        source_path = SOURCE_RECOVERED_MONTHLY_PATH if SOURCE_RECOVERED_MONTHLY_PATH.exists() else ROOT_DIR / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
        monthly = pd.read_parquet(source_path)
    if financial is None:
        financial = pd.read_csv(FINANCIAL_PATH)
    if official is None:
        official = pd.read_csv(OFFICIAL_DRIVERS_PATH)
    frame = monthly.copy()
    frame["month"] = frame["month"].astype(str)
    frame["airline_code"] = frame["airline_code"].astype(str).str.zfill(6)
    frame["announcement_date"] = pd.to_datetime(frame.get("announcement_date"), errors="coerce")
    max_year = int(pd.to_datetime(frame["month"] + "-01").dt.year.max())
    max_historical_year = min(2025, max_year)
    financial_map = _direct_financial_panel(financial, official)
    operating_map: dict[tuple[str, int, str], dict[str, object]] = {}
    for company, code in COMPANY_CODES.items():
        for year in range(2016, max_historical_year + 1):
            for period in PERIOD_MONTHS:
                operating_map[(company, year, period)] = _aggregate_period(
                    frame, code, year, period, assumption_mode=assumption_mode
                )

    rows: list[dict[str, object]] = []
    for company in COMPANY_CODES:
        for period in PERIOD_MONTHS:
            for year in range(2017, max_historical_year + 1):
                prior_fin = financial_map.get((company, year - 1, period))
                current_fin = financial_map.get((company, year, period))
                prior_ops = operating_map.get((company, year - 1, period), {})
                current_ops = operating_map.get((company, year, period), {})
                status = "historical_evaluated"
                if prior_fin is None or current_fin is None:
                    status = "insufficient_financial_history"
                elif not bool(prior_ops.get("kpi_complete")) or not bool(current_ops.get("kpi_complete")):
                    status = "insufficient_kpi_coverage"
                row = _row_base(company, year, period, status, assumption_mode)
                row["retrieved_at"] = retrieved_at or datetime.now(timezone.utc).isoformat()
                row["prior_kpi_complete"] = bool(prior_ops.get("kpi_complete", False))
                row["current_kpi_complete"] = bool(current_ops.get("kpi_complete", False))
                row["prior_kpi_latest_announcement_date"] = prior_ops.get("kpi_latest_announcement_date")
                row["current_kpi_latest_announcement_date"] = current_ops.get("kpi_latest_announcement_date")
                row["prior_kpi_logical_assumption_months"] = prior_ops.get("kpi_logical_assumption_months", 0)
                row["current_kpi_logical_assumption_months"] = current_ops.get("kpi_logical_assumption_months", 0)
                if prior_fin is not None and current_fin is not None and bool(prior_ops.get("kpi_complete")) and bool(current_ops.get("kpi_complete")):
                    _attach_period_prediction(row, prior_fin, current_fin, prior_ops, current_ops)
                else:
                    row["kpi_pit_safe"] = False
                    row["kpi_assumption_used"] = bool(prior_ops.get("kpi_assumption_used") or current_ops.get("kpi_assumption_used"))
                    row["kpi_future_imputation_used"] = bool(prior_ops.get("kpi_future_imputation_months") or current_ops.get("kpi_future_imputation_months"))
                    row["kpi_logical_assumption_months"] = int(prior_ops.get("kpi_logical_assumption_months", 0) or 0) + int(current_ops.get("kpi_logical_assumption_months", 0) or 0)
                rows.append(row)
    result = pd.DataFrame(rows)
    result["dataset_id"] = "airline_period_kpi_backtest"
    summary = _summary(result)
    out = output_path or (OUTPUT_PATH if assumption_mode == "strict_observed" else LOGICAL_OUTPUT_PATH)
    summary_out = summary_output_path or (SUMMARY_OUTPUT_PATH if assumption_mode == "strict_observed" else LOGICAL_SUMMARY_OUTPUT_PATH)
    write_csv_atomic(result, out)
    write_csv_atomic(summary, summary_out)
    return result, summary


def build_airline_period_kpi_backtest_comparison(*, retrieved_at: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build strict and logical-assumption layers plus model diagnostics."""
    strict, strict_summary = build_airline_period_kpi_backtest(retrieved_at=retrieved_at, assumption_mode="strict_observed")
    if IMPUTED_MONTHLY_PATH.exists():
        logical_monthly = pd.read_parquet(IMPUTED_MONTHLY_PATH)
    else:
        from .airline_operating_kpi_imputation import build_airline_operating_kpi_imputed

        logical_monthly = build_airline_operating_kpi_imputed(retrieved_at=retrieved_at)
    logical, logical_summary = build_airline_period_kpi_backtest(
        monthly=logical_monthly,
        assumption_mode="logical_flat_nearest_observed",
        retrieved_at=retrieved_at,
    )
    left = strict_summary.add_prefix("strict_")
    right = logical_summary.add_prefix("logical_")
    comparison = left.merge(right, left_on=["strict_company", "strict_period"], right_on=["logical_company", "logical_period"], how="outer")
    comparison["company"] = comparison["strict_company"].combine_first(comparison["logical_company"])
    comparison["period"] = comparison["strict_period"].combine_first(comparison["logical_period"])
    comparison["revenue_flat_rpk_mae_delta_logical_minus_strict_pct"] = comparison["logical_revenue_flat_rpk_mae_pct"] - comparison["strict_revenue_flat_rpk_mae_pct"]
    comparison["coverage_delta_logical_minus_strict"] = comparison["logical_historical_evaluated_rows"] - comparison["strict_historical_evaluated_rows"]
    comparison["source_quality"] = "strict_vs_logical_assumption_coverage_sensitivity"
    comparison["source_note"] = "Logical rows use a nearest observed level only when a full H1/H2/FY ASK/RPK window is otherwise unavailable; they are explicitly assumption rows and not silently promoted to observed data."
    write_csv_atomic(comparison, MODEL_COMPARISON_OUTPUT_PATH)
    diagnostics = _spring_diagnostics(logical)
    write_csv_atomic(diagnostics, SPRING_DIAGNOSTIC_OUTPUT_PATH)
    return strict, logical, comparison, diagnostics


def fetch_airline_period_kpi_backtest() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return build_airline_period_kpi_backtest_comparison()


if __name__ == "__main__":
    strict, logical, comparison, diagnostics = fetch_airline_period_kpi_backtest()
    print(
        f"Built period backtest: strict_rows={len(strict)}, logical_rows={len(logical)}, "
        f"comparison_rows={len(comparison)}, spring_diagnostics={len(diagnostics)}"
    )
