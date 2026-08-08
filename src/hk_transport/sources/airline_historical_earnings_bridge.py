"""Synchronized historical earnings bridge for mainland listed airlines.

The bridge aligns provider financial periods with issuer-released monthly
operating KPIs and period-average fuel/FX benchmarks.  Current FY2026
consensus is joined as a separate forward-looking snapshot; it is never
presented as a historical consensus vintage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR, ROOT_DIR


FINANCIAL_PATH = NORMALIZED_DIR / "airline_financial_history_trend.csv"
MONTHLY_PATH = ROOT_DIR / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
ENERGY_PATH = NORMALIZED_DIR / "airline_energy_prices.parquet"
FX_PATH = NORMALIZED_DIR / "airline_fx_rates.parquet"
CONSENSUS_PATH = NORMALIZED_DIR / "airline_consensus_snapshot.csv"
ASHARE_DETAILED_CONSENSUS_PATH = NORMALIZED_DIR / "airline_consensus_ashare_detailed.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_historical_earnings_bridge.csv"

COMPANY_CODES = {
    "Air China": "601111",
    "China Southern Airlines": "600029",
    "China Eastern Airlines": "600115",
    "Spring Airlines": "601021",
    "Hainan Airlines Holdings": "600221",
    "Juneyao Airlines": "603885",
}

FINANCIAL_METRICS = {
    "total_revenue": ("revenue_native_mn", "revenue_usd_mn"),
    "operating_cost": ("operating_cost_native_mn", "operating_cost_usd_mn"),
    "attributable_net_income": ("attributable_net_income_native_mn", "attributable_net_income_usd_mn"),
    "operating_cash_flow": ("operating_cash_flow_native_mn", "operating_cash_flow_usd_mn"),
    "basic_eps": ("basic_eps_native", None),
    "net_margin": ("net_margin_pct", None),
    "gross_margin": ("gross_margin_pct", None),
    "roe": ("roe_pct", None),
    "debt_to_assets": ("debt_to_assets_pct", None),
}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "period_end", "period_type",
    "period_start", "financial_as_of_date", "financial_point_in_time_status",
    "revenue_native_mn", "revenue_usd_mn", "operating_cost_native_mn",
    "operating_cost_usd_mn", "attributable_net_income_native_mn",
    "attributable_net_income_usd_mn", "operating_cash_flow_native_mn",
    "operating_cash_flow_usd_mn", "basic_eps_native", "net_margin_pct",
    "gross_margin_pct", "roe_pct", "debt_to_assets_pct", "ask_mn_seat_km",
    "rpk_mn_passenger_km", "passengers_mn", "cargo_tonnes",
    "passenger_load_factor_pct", "freight_load_factor_pct",
    "operating_month_count", "operating_latest_announcement_date",
    "operating_anomaly_flag",
    "jet_fuel_avg_usd_per_gallon", "jet_fuel_end_usd_per_gallon",
    "brent_avg_usd_per_barrel", "brent_end_usd_per_barrel",
    "fuel_observation_count", "fuel_latest_observation_date",
    "usd_cny_avg", "usd_hkd_avg", "fx_observation_count",
    "fx_latest_observation_date", "current_hk_broker_fy2026_net_profit_usd_mn",
    "current_hk_broker_fy2026_net_profit_low_usd_mn",
    "current_hk_broker_fy2026_net_profit_high_usd_mn",
    "current_hk_broker_count", "current_hk_broker_snapshot_date",
    "current_hk_broker_forecast_date_min", "current_hk_broker_forecast_date_max",
    "current_ashare_detailed_fy2026_net_profit_usd_mn",
    "current_ashare_detailed_snapshot_date",
    "current_ashare_detailed_forecast_date_min",
    "current_ashare_detailed_forecast_date_max",
    "source_quality", "point_in_time_status", "source_note", "retrieved_at",
]


def _period_start_and_months(period_end: pd.Timestamp, period_type: str) -> tuple[pd.Timestamp, list[str]]:
    start = pd.Timestamp(year=period_end.year, month=1, day=1)
    end_month = {"Q1_or_1Q": 3, "H1_or_2Q": 6, "Q3_or_9M": 9, "FY": 12}.get(period_type)
    if end_month is None:
        end_month = period_end.month
    months = [f"{period_end.year}-{month:02d}" for month in range(1, end_month + 1)]
    return start, months


def _metric_value(frame: pd.DataFrame, metric: str, column: str) -> float | None:
    rows = frame.loc[frame["metric"].eq(metric), column]
    if rows.empty:
        return None
    value = pd.to_numeric(rows, errors="coerce").dropna()
    return float(value.iloc[0]) if not value.empty else None


def _total_monthly_metric(frame: pd.DataFrame, code: str, months: list[str], metric: str) -> float | None:
    rows = frame.loc[
        frame["airline_code"].eq(code)
        & frame["month"].isin(months)
        & frame["metric"].eq(metric)
    ].copy()
    if rows.empty:
        return None
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    total = rows.loc[rows["region"].eq("Total")]
    monthly = total.groupby("month", as_index=False)["value"].first()
    if len(monthly) < len(months):
        regional = rows.loc[~rows["region"].eq("Total")]
        fallback = regional.groupby("month")["value"].sum(min_count=1).reset_index()
        monthly = monthly.set_index("month")["value"]
        fallback = fallback.set_index("month")["value"]
        monthly = monthly.combine_first(fallback).reset_index()
    value = pd.to_numeric(monthly["value"], errors="coerce").sum(min_count=1)
    return None if pd.isna(value) else float(value)


def _weighted_load_factor(frame: pd.DataFrame, code: str, months: list[str], numerator: str, denominator: str) -> float | None:
    numerator_value = _total_monthly_metric(frame, code, months, numerator)
    denominator_value = _total_monthly_metric(frame, code, months, denominator)
    if numerator_value is None or denominator_value in (None, 0):
        return None
    return 100.0 * numerator_value / denominator_value


def _operating_latest_announcement(frame: pd.DataFrame, code: str, months: list[str]) -> tuple[int, str | None]:
    rows = frame.loc[frame["airline_code"].eq(code) & frame["month"].isin(months)].copy()
    if rows.empty:
        return 0, None
    dates = pd.to_datetime(rows["announcement_date"], errors="coerce").dropna()
    return int(rows["month"].nunique()), (dates.max().strftime("%Y-%m-%d") if not dates.empty else None)


def _period_benchmark(frame: pd.DataFrame, period_end: pd.Timestamp, period_start: pd.Timestamp, series_id: str) -> tuple[float | None, float | None, int, str | None]:
    rows = frame.loc[
        frame["frequency"].eq("daily")
        & frame["series_id"].eq(series_id)
        & frame["metric"].eq("spot_price")
    ].copy()
    rows["observation_date"] = pd.to_datetime(rows["observation_date"], errors="coerce")
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    rows = rows.loc[rows["observation_date"].between(period_start, period_end)].dropna(subset=["observation_date", "value"])
    if rows.empty:
        return None, None, 0, None
    rows = rows.sort_values("observation_date")
    return float(rows["value"].mean()), float(rows["value"].iloc[-1]), int(len(rows)), rows["observation_date"].iloc[-1].strftime("%Y-%m-%d")


def _fx_benchmark(frame: pd.DataFrame, period_end: pd.Timestamp, period_start: pd.Timestamp, pair: str) -> tuple[float | None, int, str | None]:
    rows = frame.loc[frame["pair"].eq(pair)].copy()
    rows["observation_date"] = pd.to_datetime(rows["observation_date"], errors="coerce")
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    rows = rows.loc[rows["observation_date"].between(period_start, period_end)].dropna(subset=["observation_date", "value"])
    if rows.empty:
        return None, 0, None
    rows = rows.sort_values("observation_date")
    return float(rows["value"].mean()), int(len(rows)), rows["observation_date"].iloc[-1].strftime("%Y-%m-%d")


def _consensus_lookup(consensus: pd.DataFrame, detailed: pd.DataFrame) -> dict[str, dict[str, object]]:
    rows = consensus.loc[consensus["fiscal_year"].eq(2026)].copy()
    detailed_rows = detailed.loc[
        detailed["fiscal_year"].eq(2026) & detailed["metric"].eq("net_profit_detailed")
    ].copy()
    result: dict[str, dict[str, object]] = {}
    for _, row in rows.iterrows():
        result.setdefault(str(row["company"]), {})["hk"] = row.to_dict()
    for _, row in detailed_rows.iterrows():
        result.setdefault(str(row["company"]), {})["ashare"] = row.to_dict()
    return result


def _detailed_consensus_usd_mn(row: dict[str, object]) -> float | None:
    value = pd.to_numeric(row.get("value_avg_usd_at_snapshot"), errors="coerce")
    if pd.isna(value):
        return None
    # The source stores RMB 100 million converted to USD 100 million.
    # The bridge contract is USD million, so convert the displayed unit here.
    unit = str(row.get("native_unit", ""))
    return float(value * 100.0) if unit == "RMB 100 million" else float(value)


def build_airline_historical_earnings_bridge(
    financial: pd.DataFrame | None = None,
    monthly: pd.DataFrame | None = None,
    energy: pd.DataFrame | None = None,
    fx: pd.DataFrame | None = None,
    consensus: pd.DataFrame | None = None,
    detailed_consensus: pd.DataFrame | None = None,
    *,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    financial = financial if financial is not None else pd.read_csv(FINANCIAL_PATH)
    monthly = monthly if monthly is not None else pd.read_parquet(MONTHLY_PATH)
    energy = energy if energy is not None else pd.read_parquet(ENERGY_PATH)
    fx = fx if fx is not None else pd.read_parquet(FX_PATH)
    consensus = consensus if consensus is not None else pd.read_csv(CONSENSUS_PATH)
    detailed_consensus = detailed_consensus if detailed_consensus is not None else pd.read_csv(ASHARE_DETAILED_CONSENSUS_PATH)
    required_financial = {"company", "ticker", "period_end", "period_type", "metric", "value_native", "value_usd"}
    missing = required_financial.difference(financial.columns)
    if missing:
        raise ValueError(f"financial history is missing columns: {sorted(missing)}")

    financial = financial.copy()
    financial["period_end"] = pd.to_datetime(financial["period_end"], errors="coerce")
    financial["value_native"] = pd.to_numeric(financial["value_native"], errors="coerce")
    financial["value_usd"] = pd.to_numeric(financial["value_usd"], errors="coerce")
    monthly = monthly.copy()
    monthly["airline_code"] = monthly["airline_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    monthly["month"] = monthly["month"].astype(str).str[:7]
    consensus_by_company = _consensus_lookup(consensus, detailed_consensus)
    rows: list[dict[str, object]] = []
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()

    for (company, period_end, period_type), group in financial.groupby(["company", "period_end", "period_type"], dropna=False):
        if pd.isna(period_end) or company not in COMPANY_CODES:
            continue
        period_start, months = _period_start_and_months(period_end, str(period_type))
        code = COMPANY_CODES[company]
        row: dict[str, object] = {
            "dataset_id": "airline_historical_earnings_bridge",
            "company": company,
            "ticker": group["ticker"].iloc[0],
            "market": "CN_A",
            "period_end": period_end.strftime("%Y-%m-%d"),
            "period_type": period_type,
            "period_start": period_start.strftime("%Y-%m-%d"),
            "financial_as_of_date": period_end.strftime("%Y-%m-%d"),
            "financial_point_in_time_status": "period_end_only_no_announcement_date",
        }
        for metric, (native_name, usd_name) in FINANCIAL_METRICS.items():
            row[native_name] = _metric_value(group, metric, "value_native")
            if usd_name:
                row[usd_name] = _metric_value(group, metric, "value_usd")

        row["ask_mn_seat_km"] = _total_monthly_metric(monthly, code, months, "ask")
        row["rpk_mn_passenger_km"] = _total_monthly_metric(monthly, code, months, "rpk")
        passengers = _total_monthly_metric(monthly, code, months, "passengers")
        row["passengers_mn"] = passengers
        row["cargo_tonnes"] = _total_monthly_metric(monthly, code, months, "cargo_tonnes")
        row["passenger_load_factor_pct"] = _weighted_load_factor(monthly, code, months, "rpk", "ask")
        row["freight_load_factor_pct"] = _weighted_load_factor(monthly, code, months, "rftk", "aftk")
        row["operating_month_count"], row["operating_latest_announcement_date"] = _operating_latest_announcement(monthly, code, months)
        anomalies: list[str] = []
        if row["passenger_load_factor_pct"] is not None and row["passenger_load_factor_pct"] > 100:
            anomalies.append("passenger_load_factor_gt_100_source_anomaly")
        if row["freight_load_factor_pct"] is not None and row["freight_load_factor_pct"] > 100:
            anomalies.append("freight_load_factor_gt_100_source_anomaly")
        expected_months = {"Q1_or_1Q": 3, "H1_or_2Q": 6, "Q3_or_9M": 9, "FY": 12}.get(str(period_type), period_end.month)
        if row["operating_month_count"] < expected_months:
            anomalies.append("incomplete_operating_history")
        row["operating_anomaly_flag"] = ";".join(anomalies) if anomalies else None

        jet_avg, jet_end, jet_count, jet_latest = _period_benchmark(energy, period_end, period_start, "EER_EPJK_PF4_RGC_DPG")
        brent_avg, brent_end, _, _ = _period_benchmark(energy, period_end, period_start, "RBRTE")
        row.update({
            "jet_fuel_avg_usd_per_gallon": jet_avg,
            "jet_fuel_end_usd_per_gallon": jet_end,
            "brent_avg_usd_per_barrel": brent_avg,
            "brent_end_usd_per_barrel": brent_end,
            "fuel_observation_count": jet_count,
            "fuel_latest_observation_date": jet_latest,
        })
        cny_avg, cny_count, cny_latest = _fx_benchmark(fx, period_end, period_start, "USD_CNY")
        hkd_avg, hkd_count, hkd_latest = _fx_benchmark(fx, period_end, period_start, "USD_HKD")
        row.update({
            "usd_cny_avg": cny_avg,
            "usd_hkd_avg": hkd_avg,
            "fx_observation_count": min(cny_count, hkd_count),
            "fx_latest_observation_date": min(value for value in (cny_latest, hkd_latest) if value) if cny_latest and hkd_latest else cny_latest or hkd_latest,
        })

        current = consensus_by_company.get(company, {})
        hk = current.get("hk", {})
        ashare = current.get("ashare", {})
        row.update({
            "current_hk_broker_fy2026_net_profit_usd_mn": hk.get("net_profit_avg_usd_mn"),
            "current_hk_broker_fy2026_net_profit_low_usd_mn": hk.get("net_profit_low_usd_mn"),
            "current_hk_broker_fy2026_net_profit_high_usd_mn": hk.get("net_profit_high_usd_mn"),
            "current_hk_broker_count": hk.get("broker_count"),
            "current_hk_broker_snapshot_date": hk.get("snapshot_date"),
            "current_hk_broker_forecast_date_min": hk.get("forecast_date_min"),
            "current_hk_broker_forecast_date_max": hk.get("forecast_date_max"),
            "current_ashare_detailed_fy2026_net_profit_usd_mn": _detailed_consensus_usd_mn(ashare),
            "current_ashare_detailed_snapshot_date": ashare.get("snapshot_date"),
            "current_ashare_detailed_forecast_date_min": ashare.get("forecast_date_min"),
            "current_ashare_detailed_forecast_date_max": ashare.get("forecast_date_max"),
        })
        row["source_quality"] = "derived_multi_source_bridge"
        row["point_in_time_status"] = "mixed_period_end_financial_ops_release_benchmark_and_current_consensus_snapshot"
        row["source_note"] = (
            "Financial history is provider discovery data with period-end only and no issuer announcement date; "
            "operating KPIs retain issuer release dates; fuel and FX are sector benchmarks; current HK broker and "
            "A-share detailed consensus are separate 2026 snapshots and are not historical forecast vintages. "
            "Interim financial values may be year-to-date."
        )
        row["retrieved_at"] = retrieved
        rows.append(row)

    result = pd.DataFrame(rows)
    for column in OUTPUT_COLUMNS:
        if column not in result:
            result[column] = None
    return result[OUTPUT_COLUMNS].sort_values(["company", "period_end"]).reset_index(drop=True)


def fetch_airline_historical_earnings_bridge() -> pd.DataFrame:
    result = build_airline_historical_earnings_bridge()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
