"""Comparable H1 airline operating-trend summary from monthly issuer releases."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR, ROOT_DIR


COMPANIES = {
    "600029": "China Southern Airlines",
    "600115": "China Eastern Airlines",
    "601021": "Spring Airlines",
    "601111": "Air China",
    "603885": "Juneyao Airlines",
    "600221": "Hainan Airlines Holdings",
}

RAW_PATH = ROOT_DIR / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
TREND_COLUMNS = [
    "dataset_id", "scope_type", "airline_code", "company", "region", "metric",
    "current_period", "prior_period", "current_value", "prior_value",
    "yoy_change_abs", "yoy_change_pct", "unit", "calculation_method",
    "quality_flag", "source_quality", "source_path", "source_note", "retrieved_at",
]


def _h1_mask(frame: pd.DataFrame, period: str) -> pd.Series:
    month_dates = pd.to_datetime(frame["month"].astype(str) + "-01", errors="coerce")
    return frame["month"].astype(str).str.startswith(period) & month_dates.dt.month.le(6)


def _sum_period(frame: pd.DataFrame, *, period: str, metric: str, region: str) -> pd.Series:
    selected = frame.loc[
        _h1_mask(frame, period)
        & frame["metric"].eq(metric)
        & frame["region"].eq(region)
    ]
    return selected.groupby("airline_code")["value"].sum(min_count=1)


def _trend_row(
    *,
    scope_type: str,
    airline_code: str,
    company: str,
    region: str,
    metric: str,
    current_value: float | None,
    prior_value: float | None,
    unit: str,
    calculation_method: str,
    retrieved_at: str,
) -> dict[str, Any]:
    change_abs = None
    change_pct = None
    if current_value is not None and prior_value is not None:
        change_abs = current_value - prior_value
        if prior_value != 0:
            change_pct = 100.0 * change_abs / abs(prior_value)
    quality_flag = "large_yoy_move_review" if change_pct is not None and abs(change_pct) >= 50 else "ok"
    return {
        "dataset_id": "airline_sector_trend_snapshot",
        "scope_type": scope_type,
        "airline_code": airline_code,
        "company": company,
        "region": region,
        "metric": metric,
        "current_period": "2026H1",
        "prior_period": "2025H1",
        "current_value": current_value,
        "prior_value": prior_value,
        "yoy_change_abs": change_abs,
        "yoy_change_pct": change_pct,
        "unit": unit,
        "calculation_method": calculation_method,
        "quality_flag": quality_flag,
        "source_quality": "issuer_monthly_operating_release",
        "source_path": str(RAW_PATH),
        "source_note": (
            "Derived from the normalized monthly airline operating-release archive. "
            "Monthly values are preliminary/unaudited; H1 load factors are weighted from traffic/capacity totals."
        ),
        "retrieved_at": retrieved_at,
    }


def build_airline_sector_trends(
    frame: pd.DataFrame | None = None,
    *,
    current_period: str = "2026",
    prior_period: str = "2025",
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build company, region and six-airline-universe H1 comparisons."""
    source = frame.copy() if frame is not None else pd.read_parquet(RAW_PATH)
    required = {"month", "airline_code", "region", "metric", "value"}
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(f"monthly airline data is missing columns: {sorted(missing)}")
    source["airline_code"] = source["airline_code"].astype(str)
    source["value"] = pd.to_numeric(source["value"], errors="coerce")
    source = source.loc[source["airline_code"].isin(COMPANIES)].copy()
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    base_metrics = {
        "ask": "million seat-km", "rpk": "million passenger-km", "passengers": "thousand passengers",
        "aftk": "million freight tonne-km", "rftk": "million freight tonne-km",
        "cargo_tonnes": "tonnes", "atk": "million tonne-km", "rtk": "million tonne-km",
    }
    # Some issuer releases split traffic by region without publishing a
    # carrier-level Total row.  Build a synthetic monthly Total only for those
    # missing combinations; never replace an issuer-reported Total.
    base_source = source.loc[source["metric"].isin(base_metrics)].copy()
    total_keys = ["month", "airline_code", "metric"]
    direct_total = (
        base_source.loc[base_source["region"].eq("Total"), total_keys + ["value"]]
        .drop_duplicates(total_keys)
        .rename(columns={"value": "direct_value"})
    )
    regional_total = (
        base_source.loc[~base_source["region"].eq("Total")]
        .groupby(total_keys, as_index=False)["value"]
        .sum(min_count=1)
        .rename(columns={"value": "regional_value"})
    )
    total = regional_total.merge(direct_total, on=total_keys, how="outer")
    total["value"] = total["direct_value"].where(
        total["direct_value"].notna(), total["regional_value"]
    )
    total["region"] = "Total"
    total = total[total_keys + ["region", "value"]]
    non_total = base_source.loc[~base_source["region"].eq("Total"), total_keys + ["region", "value"]]
    source = pd.concat([non_total, total], ignore_index=True)
    regions = ("Total", "Domestic", "Regional", "International")
    for code, company in COMPANIES.items():
        for region in regions:
            for metric, unit in base_metrics.items():
                current = _sum_period(source.loc[source["airline_code"].eq(code)], period=current_period, metric=metric, region=region).get(code)
                prior = _sum_period(source.loc[source["airline_code"].eq(code)], period=prior_period, metric=metric, region=region).get(code)
                current = None if pd.isna(current) else float(current)
                prior = None if pd.isna(prior) else float(prior)
                if current is None and prior is None:
                    continue
                rows.append(_trend_row(scope_type="company", airline_code=code, company=company, region=region, metric=metric, current_value=current, prior_value=prior, unit=unit, calculation_method="sum_monthly_total_preferring_issuer_or_region_sum", retrieved_at=retrieved))

            for metric, numerator, denominator, unit in (
                ("passenger_load_factor_pct", "rpk", "ask", "%"),
                ("freight_load_factor_pct", "rftk", "aftk", "%"),
                ("overall_load_factor_pct", "rtk", "atk", "%"),
            ):
                current_num = _sum_period(source.loc[source["airline_code"].eq(code)], period=current_period, metric=numerator, region=region).get(code)
                current_den = _sum_period(source.loc[source["airline_code"].eq(code)], period=current_period, metric=denominator, region=region).get(code)
                prior_num = _sum_period(source.loc[source["airline_code"].eq(code)], period=prior_period, metric=numerator, region=region).get(code)
                prior_den = _sum_period(source.loc[source["airline_code"].eq(code)], period=prior_period, metric=denominator, region=region).get(code)
                current = float(100.0 * current_num / current_den) if pd.notna(current_num) and pd.notna(current_den) and current_den else None
                prior = float(100.0 * prior_num / prior_den) if pd.notna(prior_num) and pd.notna(prior_den) and prior_den else None
                if current is None and prior is None:
                    continue
                rows.append(_trend_row(scope_type="company", airline_code=code, company=company, region=region, metric=metric, current_value=current, prior_value=prior, unit=unit, calculation_method=f"{numerator}/{denominator} weighted H1", retrieved_at=retrieved))

    # Aggregate Total-region flows across the six-company coverage universe.
    sector = source.loc[source["region"].eq("Total")]
    for metric, unit in base_metrics.items():
        current = sector.loc[_h1_mask(sector, current_period) & sector["metric"].eq(metric)]["value"].sum(min_count=1)
        prior = sector.loc[_h1_mask(sector, prior_period) & sector["metric"].eq(metric)]["value"].sum(min_count=1)
        current = None if pd.isna(current) else float(current)
        prior = None if pd.isna(prior) else float(prior)
        if current is None and prior is None:
            continue
        rows.append(_trend_row(scope_type="sector", airline_code="SECTOR_CN_AIRLINES", company="Six-company mainland listed airline universe", region="Total", metric=metric, current_value=current, prior_value=prior, unit=unit, calculation_method="sum_company_total_monthly", retrieved_at=retrieved))
    for metric, numerator, denominator in (
        ("passenger_load_factor_pct", "rpk", "ask"),
        ("freight_load_factor_pct", "rftk", "aftk"),
        ("overall_load_factor_pct", "rtk", "atk"),
    ):
        values: dict[str, float | None] = {}
        for period in (current_period, prior_period):
            num = sector.loc[_h1_mask(sector, period) & sector["metric"].eq(numerator)]["value"].sum(min_count=1)
            den = sector.loc[_h1_mask(sector, period) & sector["metric"].eq(denominator)]["value"].sum(min_count=1)
            values[period] = float(100.0 * num / den) if pd.notna(num) and pd.notna(den) and den else None
        rows.append(_trend_row(scope_type="sector", airline_code="SECTOR_CN_AIRLINES", company="Six-company mainland listed airline universe", region="Total", metric=metric, current_value=values[current_period], prior_value=values[prior_period], unit="%", calculation_method=f"{numerator}/{denominator} weighted H1", retrieved_at=retrieved))
    return pd.DataFrame(rows, columns=TREND_COLUMNS)


def fetch_airline_sector_trends() -> pd.DataFrame:
    result = build_airline_sector_trends()
    result.to_csv(NORMALIZED_DIR / "airline_sector_trend_snapshot.csv", index=False)
    return result


def source_path() -> Path:
    return NORMALIZED_DIR / "airline_sector_trend_snapshot.csv"
