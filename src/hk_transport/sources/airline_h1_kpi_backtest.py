"""Historical 1H KPI-to-earnings calibration for the airline event thesis.

This is deliberately narrower than the FY2026 scenario bridge.  It asks a
specific event question: if we knew the January--June ASK/RPK releases before
the interim report, how well would a transparent flat-unit-economics bridge
estimate the subsequent 1H revenue, operating cost and attributable profit?

The historical financial panel is provider history with period-end dates and
does not expose a complete historical issuer announcement-date tape.  Those
rows are therefore labelled calibration-only and must not be described as a
strict announcement-date PIT backtest.  Monthly operating inputs retain their
CNINFO announcement dates and are checked against an August 1 pre-report
cutoff.  The current 2026 row is a nowcast with no target actuals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR, ROOT_DIR


MONTHLY_PATH = ROOT_DIR / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
FINANCIAL_PATH = NORMALIZED_DIR / "airline_financial_history_trend.csv"
OFFICIAL_DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
INDEPENDENT_PATH = NORMALIZED_DIR / "airline_independent_forecast_view.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_h1_kpi_backtest.csv"
SUMMARY_OUTPUT_PATH = NORMALIZED_DIR / "airline_h1_kpi_backtest_summary.csv"
IMPUTED_MONTHLY_PATH = NORMALIZED_DIR / "airline_operating_kpi_imputed.parquet"
IMPUTED_OUTPUT_PATH = NORMALIZED_DIR / "airline_h1_kpi_backtest_imputed.csv"
IMPUTED_SUMMARY_OUTPUT_PATH = NORMALIZED_DIR / "airline_h1_kpi_backtest_imputed_summary.csv"
COMPARISON_OUTPUT_PATH = NORMALIZED_DIR / "airline_h1_kpi_backtest_raw_vs_imputed.csv"


COMPANY_CODES = {
    "Air China": "601111",
    "China Southern Airlines": "600029",
    "China Eastern Airlines": "600115",
    "Spring Airlines": "601021",
    "Hainan Airlines Holdings": "600221",
    "Juneyao Airlines": "603885",
}

FINANCIAL_METRICS = ("total_revenue", "operating_cost", "attributable_net_income", "fuel_cost")
OPERATING_METRICS = ("ask", "rpk")


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _date_text(value: object) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _h1_months(year: int) -> list[str]:
    return [f"{year}-{month:02d}" for month in range(1, 7)]


def _monthly_metric_total(frame: pd.DataFrame, code: str, months: list[str], metric: str) -> tuple[float | None, int, str | None, int, int]:
    """Aggregate a metric to H1, preferring issuer Total rows by month."""
    rows = frame.loc[
        frame["airline_code"].astype(str).eq(str(code))
        & frame["month"].isin(months)
        & frame["metric"].eq(metric)
    ].copy()
    if rows.empty:
        return None, 0, None, 0, 0
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    month_values: list[float] = []
    used_rows: list[pd.Series] = []
    for month, group in rows.groupby("month", sort=True):
        total = group.loc[group["region"].astype(str).str.lower().eq("total")]
        selected_rows = total.loc[total["value"].notna()]
        selected = selected_rows["value"].iloc[0] if not selected_rows.empty else None
        if selected is None:
            selected_values = group.loc[~group["region"].astype(str).str.lower().eq("total"), "value"].dropna()
            selected = selected_values.sum() if not selected_values.empty else None
            selected_rows = group.loc[
                ~group["region"].astype(str).str.lower().eq("total")
                & group["value"].notna()
            ]
        if selected is not None and not pd.isna(selected):
            month_values.append(float(selected))
            used_rows.extend([row for _, row in selected_rows.iterrows()])
    if len(month_values) != len(months):
        return None, len(month_values), None, 0, 0
    used = pd.DataFrame(used_rows) if used_rows else rows.iloc[0:0]
    announcement_dates = pd.to_datetime(used["announcement_date"], errors="coerce").dropna()
    latest = announcement_dates.max().strftime("%Y-%m-%d") if not announcement_dates.empty else None
    if "observation_status" in used.columns:
        imputed_count = int(used["observation_status"].astype(str).eq("imputed").sum())
    else:
        imputed_count = 0
    if "uses_future_observation" in used.columns:
        future_count = int(pd.Series(used["uses_future_observation"]).fillna(False).astype(bool).sum())
    else:
        future_count = 0
    return float(sum(month_values)), len(month_values), latest, imputed_count, future_count


def _operating_h1(frame: pd.DataFrame, code: str, year: int) -> dict[str, object]:
    months = _h1_months(year)
    result: dict[str, object] = {
        "company_code": str(code),
        "year": year,
        "h1_kpi_months_expected": 6,
        "h1_kpi_latest_announcement_date": None,
        "h1_kpi_source_quality": "issuer_cninfo_operating_release",
    }
    latest_dates: list[pd.Timestamp] = []
    complete = True
    for metric in OPERATING_METRICS:
        value, month_count, latest, imputed_count, future_count = _monthly_metric_total(frame, code, months, metric)
        result[f"h1_{metric}_mn"] = value
        result[f"h1_{metric}_months_available"] = month_count
        result[f"h1_{metric}_imputed_months"] = imputed_count
        result[f"h1_{metric}_future_imputation_months"] = future_count
        result["h1_kpi_imputation_used"] = bool(result.get("h1_kpi_imputation_used", False) or imputed_count > 0)
        result["h1_kpi_future_imputation_used"] = bool(result.get("h1_kpi_future_imputation_used", False) or future_count > 0)
        if value is None:
            complete = False
        parsed = pd.to_datetime(latest, errors="coerce")
        if not pd.isna(parsed):
            latest_dates.append(parsed)
    ask = _num(result.get("h1_ask_mn"))
    rpk = _num(result.get("h1_rpk_mn"))
    result["h1_load_factor_pct"] = 100.0 * rpk / ask if rpk is not None and ask else None
    result["h1_kpi_complete"] = complete
    result["h1_kpi_pit_safe_for_h1_event"] = not bool(result.get("h1_kpi_future_imputation_used", False))
    if latest_dates:
        result["h1_kpi_latest_announcement_date"] = max(latest_dates).strftime("%Y-%m-%d")
    return result


def _financial_panel(financial: pd.DataFrame, official: pd.DataFrame) -> dict[tuple[str, int], dict[str, object]]:
    """Return one H1 financial row per company/year, with 1H2025 primary override."""
    provider = financial.loc[
        financial["statement_period"].astype(str).str.endswith("-06")
        & financial["metric"].isin(FINANCIAL_METRICS)
    ].copy()
    provider["year"] = pd.to_numeric(provider["statement_period"].astype(str).str[:4], errors="coerce")
    result: dict[tuple[str, int], dict[str, object]] = {}
    for (company, year), group in provider.groupby(["company", "year"], sort=True):
        row: dict[str, object] = {
            "company": str(company),
            "year": int(year),
            "financial_source_quality": "akshare_discovery_historical",
            "financial_point_in_time_status": "period_end_only_no_announcement_date",
            "financial_announcement_date": None,
            "financial_source_path": str(FINANCIAL_PATH),
            "financial_source_url": None,
            "financial_fx_native_per_usd": None,
        }
        for metric in FINANCIAL_METRICS:
            values = pd.to_numeric(group.loc[group["metric"].eq(metric), "value_native"], errors="coerce").dropna()
            row[metric] = float(values.iloc[0]) if not values.empty else None
        result[(str(company), int(year))] = row

    if official.empty:
        return result
    official = official.loc[official["statement_period"].eq("1H2025")].copy()
    for company, group in official.groupby("company", sort=True):
        row = result.setdefault(
            (str(company), 2025),
            {
                "company": str(company),
                "year": 2025,
                "financial_source_quality": "primary_issuer",
                "financial_point_in_time_status": "issuer_announcement_date_available",
                "financial_announcement_date": None,
                "financial_source_path": str(OFFICIAL_DRIVERS_PATH),
                "financial_source_url": None,
                "financial_fx_native_per_usd": None,
            },
        )
        # The primary parser uses profit_total where attributable net income is
        # not separately present.  Keep that fallback explicit in the source
        # quality field rather than silently treating it as the same measure.
        for metric in ("total_revenue", "operating_cost", "attributable_net_income", "fuel_cost"):
            selected = group.loc[group["metric"].eq(metric), "value_native"]
            if metric == "attributable_net_income" and selected.empty:
                selected = group.loc[group["metric"].eq("profit_total"), "value_native"]
                if not selected.empty:
                    row["financial_profit_metric"] = "profit_total_fallback"
            values = pd.to_numeric(selected, errors="coerce").dropna()
            if not values.empty:
                row[metric] = float(values.iloc[0])
        announced = pd.to_datetime(group["announced_at"], errors="coerce").dropna()
        if not announced.empty:
            row["financial_announcement_date"] = announced.iloc[0].strftime("%Y-%m-%d")
        urls = group["source_url"].dropna().astype(str)
        if not urls.empty:
            row["financial_source_url"] = urls.iloc[0]
        fx = pd.to_numeric(group["fx_value"], errors="coerce").dropna()
        if not fx.empty:
            row["financial_fx_native_per_usd"] = float(fx.iloc[0])
        row["financial_source_quality"] = "primary_issuer"
        row["financial_point_in_time_status"] = "issuer_announcement_date_available"
        row["financial_source_path"] = str(OFFICIAL_DRIVERS_PATH)
    return result


def _independent_base(independent: pd.DataFrame) -> dict[str, dict[str, float | None]]:
    if independent.empty:
        return {}
    rows = independent.loc[
        independent["scenario"].eq("base")
        & independent["company"].isin(["Spring Airlines", "Juneyao Airlines"])
    ]
    result: dict[str, dict[str, float | None]] = {}
    for _, row in rows.iterrows():
        result[str(row["company"])] = {
            "yield_mix_growth_pct": _num(row.get("yield_mix_growth_assumption_pct")),
            "fuel_shock_pct": _num(row.get("fuel_price_shock_assumption_pct")),
            "nonfuel_growth_pct": _num(row.get("nonfuel_cost_per_ask_growth_assumption_pct")),
        }
    return result


def _row_base(company: str, year: int, status: str, input_layer: str) -> dict[str, object]:
    return {
        "dataset_id": "airline_h1_kpi_backtest",
        "company": company,
        "ticker": f"{COMPANY_CODES[company]}.SH",
        "statement_period": f"1H{year}",
        "target_year": year,
        "row_status": status,
        "kpi_input_layer": input_layer,
        "model_name": "flat_unit_economics_ask",
        "kpi_information_cutoff": f"{year}-08-01",
        "target_actual_source_quality": None,
        "target_actual_pit_status": None,
        "target_financial_announcement_date": None,
        "source_quality": "derived_historical_calibration",
        "source_note": (
            "Historical KPI inputs retain issuer monthly announcement dates; financial target/base rows use provider period-end history unless explicitly overridden by the 1H2025 primary report. "
            "This is calibration evidence, not a complete historical announcement-date PIT backtest."
        ),
    }


def _attach_prediction(row: dict[str, object], prior_fin: dict[str, object], current_fin: dict[str, object] | None, prior_ops: dict[str, object], current_ops: dict[str, object]) -> None:
    prev_ask = _num(prior_ops.get("h1_ask_mn"))
    cur_ask = _num(current_ops.get("h1_ask_mn"))
    prev_rpk = _num(prior_ops.get("h1_rpk_mn"))
    cur_rpk = _num(current_ops.get("h1_rpk_mn"))
    row["prior_h1_ask_mn"] = prev_ask
    row["current_h1_ask_mn"] = cur_ask
    row["prior_h1_rpk_mn"] = prev_rpk
    row["current_h1_rpk_mn"] = cur_rpk
    row["prior_h1_load_factor_pct"] = _num(prior_ops.get("h1_load_factor_pct"))
    row["current_h1_load_factor_pct"] = _num(current_ops.get("h1_load_factor_pct"))
    row["ask_growth_pct"] = 100.0 * cur_ask / prev_ask - 100.0 if cur_ask and prev_ask else None
    row["rpk_growth_pct"] = 100.0 * cur_rpk / prev_rpk - 100.0 if cur_rpk and prev_rpk else None
    row["load_factor_change_pp"] = (
        _num(current_ops.get("h1_load_factor_pct")) - _num(prior_ops.get("h1_load_factor_pct"))
        if _num(current_ops.get("h1_load_factor_pct")) is not None and _num(prior_ops.get("h1_load_factor_pct")) is not None
        else None
    )
    row["rpk_minus_ask_growth_gap_pp"] = (
        row["rpk_growth_pct"] - row["ask_growth_pct"]
        if row["rpk_growth_pct"] is not None and row["ask_growth_pct"] is not None
        else None
    )
    row["kpi_latest_announcement_date"] = current_ops.get("h1_kpi_latest_announcement_date")
    latest = pd.to_datetime(row["kpi_latest_announcement_date"], errors="coerce")
    cutoff = pd.to_datetime(row["kpi_information_cutoff"], errors="coerce")
    row["kpi_pre_report_cutoff_pass"] = bool(not pd.isna(latest) and not pd.isna(cutoff) and latest <= cutoff)
    row["kpi_complete"] = bool(current_ops.get("h1_kpi_complete") and prior_ops.get("h1_kpi_complete"))
    row["prior_h1_kpi_imputation_used"] = bool(prior_ops.get("h1_kpi_imputation_used", False))
    row["current_h1_kpi_imputation_used"] = bool(current_ops.get("h1_kpi_imputation_used", False))
    row["kpi_imputation_used"] = bool(row["prior_h1_kpi_imputation_used"] or row["current_h1_kpi_imputation_used"])
    row["kpi_future_imputation_used"] = bool(
        prior_ops.get("h1_kpi_future_imputation_used", False)
        or current_ops.get("h1_kpi_future_imputation_used", False)
    )
    row["kpi_pit_safe_for_h1_event"] = bool(
        prior_ops.get("h1_kpi_pit_safe_for_h1_event", True)
        and current_ops.get("h1_kpi_pit_safe_for_h1_event", True)
    )

    prev_revenue = _num(prior_fin.get("total_revenue"))
    prev_cost = _num(prior_fin.get("operating_cost"))
    prev_profit = _num(prior_fin.get("attributable_net_income"))
    current_revenue = _num(current_fin.get("total_revenue")) if current_fin else None
    current_cost = _num(current_fin.get("operating_cost")) if current_fin else None
    current_profit = _num(current_fin.get("attributable_net_income")) if current_fin else None
    ask_factor = 1.0 + row["ask_growth_pct"] / 100.0 if row["ask_growth_pct"] is not None else None
    rpk_factor = 1.0 + row["rpk_growth_pct"] / 100.0 if row["rpk_growth_pct"] is not None else None
    row["prior_h1_revenue_native_mn"] = prev_revenue
    row["prior_h1_operating_cost_native_mn"] = prev_cost
    row["prior_h1_attributable_profit_native_mn"] = prev_profit
    row["target_h1_revenue_native_mn"] = current_revenue
    row["target_h1_operating_cost_native_mn"] = current_cost
    row["target_h1_attributable_profit_native_mn"] = current_profit
    row["flat_ask_revenue_pred_native_mn"] = prev_revenue * ask_factor if prev_revenue is not None and ask_factor is not None else None
    row["flat_rpk_revenue_pred_native_mn"] = prev_revenue * rpk_factor if prev_revenue is not None and rpk_factor is not None else None
    row["flat_ask_cost_pred_native_mn"] = prev_cost * ask_factor if prev_cost is not None and ask_factor is not None else None
    flat_revenue = _num(row.get("flat_ask_revenue_pred_native_mn"))
    flat_cost = _num(row.get("flat_ask_cost_pred_native_mn"))
    flat_op = flat_revenue - flat_cost if flat_revenue is not None and flat_cost is not None else None
    prev_op = prev_revenue - prev_cost if prev_revenue is not None and prev_cost is not None else None
    net_to_op = prev_profit / prev_op if prev_profit is not None and prev_op and prev_op > 0 else None
    row["prior_h1_net_to_operating_conversion"] = net_to_op
    row["flat_ask_operating_profit_pred_native_mn"] = flat_op
    row["flat_ask_profit_pred_native_mn"] = flat_op * net_to_op if flat_op is not None and net_to_op is not None else None
    row["flat_ask_profit_pred_status"] = "positive_prior_h1_operating_to_net_conversion" if net_to_op is not None else "unavailable_prior_h1_loss_or_missing"
    row["revenue_per_ask_actual_growth_pct"] = (
        100.0 * (current_revenue / _num(current_ops.get("h1_ask_mn"))) / (prev_revenue / prev_ask) - 100.0
        if current_revenue is not None and prev_revenue is not None and cur_ask and prev_ask and prev_revenue and current_revenue
        else None
    )
    row["cost_per_ask_actual_growth_pct"] = (
        100.0 * (current_cost / cur_ask) / (prev_cost / prev_ask) - 100.0
        if current_cost is not None and prev_cost is not None and cur_ask and prev_ask and prev_cost and current_cost
        else None
    )
    row["target_actual_source_quality"] = current_fin.get("financial_source_quality") if current_fin else None
    row["target_financial_source_quality"] = current_fin.get("financial_source_quality") if current_fin else None
    row["target_actual_pit_status"] = current_fin.get("financial_point_in_time_status") if current_fin else None
    row["target_financial_announcement_date"] = current_fin.get("financial_announcement_date") if current_fin else None
    row["target_financial_source_path"] = current_fin.get("financial_source_path") if current_fin else None
    row["prior_financial_source_quality"] = prior_fin.get("financial_source_quality")
    row["prior_financial_pit_status"] = prior_fin.get("financial_point_in_time_status")
    row["prior_financial_source_path"] = prior_fin.get("financial_source_path")

    if current_fin is not None:
        row["revenue_error_flat_ask_pct"] = 100.0 * flat_revenue / current_revenue - 100.0 if flat_revenue is not None and current_revenue else None
        row["revenue_error_flat_rpk_pct"] = 100.0 * _num(row.get("flat_rpk_revenue_pred_native_mn")) / current_revenue - 100.0 if _num(row.get("flat_rpk_revenue_pred_native_mn")) is not None and current_revenue else None
        row["operating_cost_error_flat_ask_pct"] = 100.0 * flat_cost / current_cost - 100.0 if flat_cost is not None and current_cost else None
        row["profit_error_flat_ask_native_mn"] = _num(row.get("flat_ask_profit_pred_native_mn")) - current_profit if _num(row.get("flat_ask_profit_pred_native_mn")) is not None and current_profit is not None else None
        row["profit_direction_correct_flat_ask"] = (
            bool(np.sign(_num(row.get("flat_ask_profit_pred_native_mn"))) == np.sign(current_profit))
            if _num(row.get("flat_ask_profit_pred_native_mn")) is not None and current_profit is not None
            else None
        )
        row["actual_revenue_growth_vs_prior_h1_pct"] = 100.0 * current_revenue / prev_revenue - 100.0 if current_revenue is not None and prev_revenue else None
        row["actual_cost_growth_vs_prior_h1_pct"] = 100.0 * current_cost / prev_cost - 100.0 if current_cost is not None and prev_cost else None
    else:
        for field in (
            "revenue_error_flat_ask_pct", "revenue_error_flat_rpk_pct", "operating_cost_error_flat_ask_pct",
            "profit_error_flat_ask_native_mn", "profit_direction_correct_flat_ask",
            "actual_revenue_growth_vs_prior_h1_pct", "actual_cost_growth_vs_prior_h1_pct",
        ):
            row[field] = None


def _attach_current_analyst_nowcast(row: dict[str, object], company: str, prior_fin: dict[str, object], assumptions: dict[str, dict[str, float | None]]) -> None:
    config = assumptions.get(company)
    if not config:
        return
    ask_growth = _num(row.get("ask_growth_pct"))
    prior_revenue = _num(prior_fin.get("total_revenue"))
    prior_cost = _num(prior_fin.get("operating_cost"))
    prior_profit = _num(prior_fin.get("attributable_net_income"))
    prior_fuel = _num(prior_fin.get("fuel_cost"))
    if ask_growth is None or prior_revenue is None or prior_cost is None:
        return
    mix = config.get("yield_mix_growth_pct")
    fuel_shock = config.get("fuel_shock_pct") or 0.0
    nonfuel_growth = config.get("nonfuel_growth_pct")
    row["analyst_yield_mix_growth_pct"] = mix
    row["analyst_fuel_shock_pct"] = fuel_shock
    row["analyst_nonfuel_cost_per_ask_growth_pct"] = nonfuel_growth
    ask_factor = 1.0 + ask_growth / 100.0
    revenue = prior_revenue * ask_factor * (1.0 + mix / 100.0) if mix is not None else None
    row["analyst_h1_revenue_pred_native_mn"] = revenue
    if prior_fuel is None or nonfuel_growth is None:
        row["analyst_h1_cost_pred_native_mn"] = None
        row["analyst_h1_profit_pred_native_mn"] = None
        row["analyst_h1_nowcast_status"] = "missing_h1_2025_fuel_or_nonfuel_anchor"
        return
    prior_nonfuel = prior_cost - prior_fuel
    fuel = prior_fuel * ask_factor * (1.0 + fuel_shock / 100.0)
    nonfuel = prior_nonfuel * ask_factor * (1.0 + nonfuel_growth / 100.0)
    cost = fuel + nonfuel
    op = revenue - cost if revenue is not None else None
    prev_op = prior_revenue - prior_cost
    ratio = prior_profit / prev_op if prior_profit is not None and prev_op > 0 else None
    row["analyst_h1_fuel_cost_pred_native_mn"] = fuel
    row["analyst_h1_nonfuel_cost_pred_native_mn"] = nonfuel
    row["analyst_h1_cost_pred_native_mn"] = cost
    row["analyst_h1_operating_profit_pred_native_mn"] = op
    row["analyst_h1_profit_pred_native_mn"] = op * ratio if op is not None and ratio is not None else None
    row["analyst_h1_nowcast_status"] = "current_h1_2026_analyst_assumption_bridge"


def _to_usd(value: object, fx: object) -> float | None:
    value_n = _num(value)
    fx_n = _num(fx)
    return value_n / fx_n if value_n is not None and fx_n else None


def _summary(rows: pd.DataFrame) -> pd.DataFrame:
    historical = rows.loc[rows["row_status"].eq("historical_evaluated")].copy()
    output: list[dict[str, object]] = []
    for company in COMPANY_CODES:
        group = historical.loc[historical["company"].eq(company)]
        profit_valid = group.dropna(subset=["profit_direction_correct_flat_ask"])
        row: dict[str, object] = {
            "dataset_id": "airline_h1_kpi_backtest_summary",
            "company": company,
            "ticker": f"{COMPANY_CODES[company]}.SH",
            "historical_evaluated_rows": int(len(group)),
            "historical_year_min": int(group["target_year"].min()) if not group.empty else None,
            "historical_year_max": int(group["target_year"].max()) if not group.empty else None,
            "revenue_flat_ask_mae_pct": float(group["revenue_error_flat_ask_pct"].abs().mean()) if not group.empty else None,
            "revenue_flat_ask_bias_pct": float(group["revenue_error_flat_ask_pct"].mean()) if not group.empty else None,
            "revenue_flat_rpk_mae_pct": float(group["revenue_error_flat_rpk_pct"].abs().mean()) if not group.empty else None,
            "operating_cost_flat_ask_mae_pct": float(group["operating_cost_error_flat_ask_pct"].abs().mean()) if not group.empty else None,
            "profit_direction_valid_rows": int(len(profit_valid)),
            "profit_direction_accuracy": float(profit_valid["profit_direction_correct_flat_ask"].mean()) if not profit_valid.empty else None,
            "kpi_imputation_used_historical_rows": int(group["kpi_imputation_used"].fillna(False).astype(bool).sum()) if "kpi_imputation_used" in group.columns else 0,
            "kpi_future_imputation_historical_rows": int(group["kpi_future_imputation_used"].fillna(False).astype(bool).sum()) if "kpi_future_imputation_used" in group.columns else 0,
            "kpi_pit_safe_historical_rows": int(group["kpi_pit_safe_for_h1_event"].fillna(False).astype(bool).sum()) if "kpi_pit_safe_for_h1_event" in group.columns else 0,
            "revenue_per_ask_actual_median_growth_pct": float(group["revenue_per_ask_actual_growth_pct"].median()) if not group.empty else None,
            "revenue_per_ask_actual_p25_growth_pct": float(group["revenue_per_ask_actual_growth_pct"].quantile(0.25)) if not group.empty else None,
            "revenue_per_ask_actual_p75_growth_pct": float(group["revenue_per_ask_actual_growth_pct"].quantile(0.75)) if not group.empty else None,
            "cost_per_ask_actual_median_growth_pct": float(group["cost_per_ask_actual_growth_pct"].median()) if not group.empty else None,
            "cost_per_ask_actual_p25_growth_pct": float(group["cost_per_ask_actual_growth_pct"].quantile(0.25)) if not group.empty else None,
            "cost_per_ask_actual_p75_growth_pct": float(group["cost_per_ask_actual_growth_pct"].quantile(0.75)) if not group.empty else None,
            "source_quality": "historical_calibration_not_strict_pit_backtest",
            "source_note": "Financial targets before 1H2025 do not retain issuer announcement dates; use this to calibrate KPI sensitivity, not to claim an executable historical event backtest.",
        }
        current = rows.loc[(rows["company"].eq(company)) & rows["row_status"].eq("current_1h2026_nowcast")]
        if not current.empty:
            latest = current.iloc[0]
            fx = latest.get("current_financial_fx_native_per_usd")
            for field in (
                "flat_ask_revenue_pred_native_mn", "flat_ask_cost_pred_native_mn", "flat_ask_profit_pred_native_mn",
                "analyst_h1_revenue_pred_native_mn", "analyst_h1_cost_pred_native_mn", "analyst_h1_profit_pred_native_mn",
            ):
                row[field.replace("_native_mn", "_usd_mn")] = _to_usd(latest.get(field), fx)
            row["current_kpi_cutoff"] = latest.get("kpi_information_cutoff")
            row["current_kpi_latest_announcement_date"] = latest.get("kpi_latest_announcement_date")
        output.append(row)
    return pd.DataFrame(output)


def build_airline_h1_kpi_backtest(
    *,
    monthly: pd.DataFrame | None = None,
    financial: pd.DataFrame | None = None,
    official: pd.DataFrame | None = None,
    independent: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
    input_layer: str = "raw_observed",
    output_path: Path = OUTPUT_PATH,
    summary_output_path: Path = SUMMARY_OUTPUT_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build historical 1H calibration rows plus a current 1H2026 nowcast."""
    monthly = monthly if monthly is not None else pd.read_parquet(MONTHLY_PATH)
    financial = financial if financial is not None else pd.read_csv(FINANCIAL_PATH)
    official = official if official is not None else pd.read_csv(OFFICIAL_DRIVERS_PATH)
    independent = independent if independent is not None else pd.read_csv(INDEPENDENT_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    monthly = monthly.copy()
    monthly["month"] = monthly["month"].astype(str)
    monthly["announcement_date"] = pd.to_datetime(monthly["announcement_date"], errors="coerce")
    max_year = int(pd.to_datetime(monthly["month"] + "-01").dt.year.max())
    financial_map = _financial_panel(financial, official)
    operating_map: dict[tuple[str, int], dict[str, object]] = {}
    for company, code in COMPANY_CODES.items():
        for year in range(2016, max_year + 1):
            operating_map[(company, year)] = _operating_h1(monthly, code, year)
    independent_assumptions = _independent_base(independent)

    rows: list[dict[str, object]] = []
    for company in COMPANY_CODES:
        for year in range(2017, max_year + 1):
            prior_fin = financial_map.get((company, year - 1))
            current_fin = financial_map.get((company, year)) if year < max_year else None
            prior_ops = operating_map.get((company, year - 1), {})
            current_ops = operating_map.get((company, year), {})
            status = "current_1h2026_nowcast" if year == max_year else "historical_evaluated"
            row = _row_base(company, year, status, input_layer)
            row["retrieved_at"] = retrieved
            if not prior_fin:
                row["row_status"] = "insufficient_prior_financial_base"
                rows.append(row)
                continue
            if not bool(prior_ops.get("h1_kpi_complete")) or not bool(current_ops.get("h1_kpi_complete")):
                row["row_status"] = "insufficient_h1_kpi_coverage" if year < max_year else "current_1h2026_kpi_coverage_gap"
                row["prior_h1_ask_months_available"] = prior_ops.get("h1_ask_months_available")
                row["current_h1_ask_months_available"] = current_ops.get("h1_ask_months_available")
                row["prior_h1_rpk_months_available"] = prior_ops.get("h1_rpk_months_available")
                row["current_h1_rpk_months_available"] = current_ops.get("h1_rpk_months_available")
                row["kpi_latest_announcement_date"] = current_ops.get("h1_kpi_latest_announcement_date")
                latest = pd.to_datetime(row["kpi_latest_announcement_date"], errors="coerce")
                cutoff = pd.to_datetime(row["kpi_information_cutoff"], errors="coerce")
                row["kpi_pre_report_cutoff_pass"] = bool(not pd.isna(latest) and not pd.isna(cutoff) and latest <= cutoff)
                row["kpi_complete"] = False
                row["prior_h1_kpi_imputation_used"] = bool(prior_ops.get("h1_kpi_imputation_used", False))
                row["current_h1_kpi_imputation_used"] = bool(current_ops.get("h1_kpi_imputation_used", False))
                row["kpi_imputation_used"] = bool(row["prior_h1_kpi_imputation_used"] or row["current_h1_kpi_imputation_used"])
                row["kpi_future_imputation_used"] = bool(
                    prior_ops.get("h1_kpi_future_imputation_used", False)
                    or current_ops.get("h1_kpi_future_imputation_used", False)
                )
                row["kpi_pit_safe_for_h1_event"] = bool(
                    prior_ops.get("h1_kpi_pit_safe_for_h1_event", True)
                    and current_ops.get("h1_kpi_pit_safe_for_h1_event", True)
                )
                row["retrieved_at"] = retrieved
                rows.append(row)
                continue
            _attach_prediction(row, prior_fin, current_fin, prior_ops, current_ops)
            if current_fin is None:
                _attach_current_analyst_nowcast(row, company, {**prior_fin}, independent_assumptions)
                row["current_financial_fx_native_per_usd"] = prior_fin.get("financial_fx_native_per_usd")
                row["target_actual_source_quality"] = "pending_1H2026_primary_report"
                row["target_actual_pit_status"] = "pending_formal_interim_report"
                row["source_quality"] = "current_pre_event_nowcast"
                row["source_note"] = (
                    "Current 1H2026 nowcast uses H1 2026 issuer operating releases through the pre-report cutoff and H1 2025 financial base. "
                    "No 1H2026 financial actual is used as an input; the formal interim report remains the event test."
                )
            rows.append(row)

    result = pd.DataFrame(rows)
    result["dataset_id"] = "airline_h1_kpi_backtest"
    result.to_csv(output_path, index=False)
    summary = _summary(result)
    summary["retrieved_at"] = retrieved
    summary.to_csv(summary_output_path, index=False)
    return result, summary


def fetch_airline_h1_kpi_backtest() -> tuple[pd.DataFrame, pd.DataFrame]:
    return build_airline_h1_kpi_backtest()


def build_airline_h1_kpi_backtest_comparison(
    *,
    imputed_monthly: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run raw and source-recovered/research-imputed H1 calibration side by side."""
    raw, raw_summary = build_airline_h1_kpi_backtest(retrieved_at=retrieved_at)
    if imputed_monthly is None:
        if not IMPUTED_MONTHLY_PATH.exists():
            from .airline_operating_kpi_imputation import build_airline_operating_kpi_imputed

            build_airline_operating_kpi_imputed(retrieved_at=retrieved_at)
        imputed_monthly = pd.read_parquet(IMPUTED_MONTHLY_PATH)
    imputed, imputed_summary = build_airline_h1_kpi_backtest(
        monthly=imputed_monthly,
        retrieved_at=retrieved_at,
        input_layer="source_recovered_plus_research_imputed",
        output_path=IMPUTED_OUTPUT_PATH,
        summary_output_path=IMPUTED_SUMMARY_OUTPUT_PATH,
    )
    left = raw_summary.add_prefix("raw_")
    right = imputed_summary.add_prefix("imputed_")
    comparison = left.merge(
        right,
        left_on="raw_company",
        right_on="imputed_company",
        how="outer",
    )
    comparison["company"] = comparison["raw_company"].combine_first(comparison["imputed_company"])
    comparison["revenue_mae_delta_imputed_minus_raw_pct"] = (
        comparison["imputed_revenue_flat_ask_mae_pct"] - comparison["raw_revenue_flat_ask_mae_pct"]
    )
    comparison["cost_mae_delta_imputed_minus_raw_pct"] = (
        comparison["imputed_operating_cost_flat_ask_mae_pct"] - comparison["raw_operating_cost_flat_ask_mae_pct"]
    )
    comparison["historical_rows_delta_imputed_minus_raw"] = (
        comparison["imputed_historical_evaluated_rows"] - comparison["raw_historical_evaluated_rows"]
    )
    comparison["source_quality"] = "raw_vs_source_recovered_imputed_sensitivity"
    comparison["source_note"] = (
        "The imputed layer includes official-PDF source recoveries plus short-gap interpolation. Only rows flagged with future interpolation are not PIT-safe for the 1H2026 event model; use this as historical calibration sensitivity, not as an executable backtest."
    )
    comparison.to_csv(COMPARISON_OUTPUT_PATH, index=False)
    return raw, imputed, comparison


def fetch_airline_h1_kpi_backtest_comparison() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return build_airline_h1_kpi_backtest_comparison()
