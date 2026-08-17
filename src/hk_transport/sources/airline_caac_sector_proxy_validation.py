"""Validate CAAC sector demand/cargo proxies against issuer operating KPIs.

This is deliberately a proxy-validation layer, not a claim that sector
volume equals a company's revenue.  It asks a narrower and testable question:
when CAAC reports China-wide passenger/cargo growth, how close is that signal
to each listed airline's observed passenger/cargo-tonne growth over the same
H1 or FY window?

Company rows are restricted to ``observation_status == observed`` from the
research operating layer.  CAAC YTD observations retain their release date.
The output is labelled evaluation evidence because a full-year December CAAC
release arrives after year-end and may not be available before an annual
earnings forecast cutoff.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR


COMPANY_CODES = {
    "Air China": "601111",
    "China Southern Airlines": "600029",
    "China Eastern Airlines": "600115",
    "Spring Airlines": "601021",
    "Hainan Airlines Holdings": "600221",
    "Juneyao Airlines": "603885",
}

OPERATING_PATH = NORMALIZED_DIR / "airline_operating_kpi_imputed.parquet"
CAAC_PATH = NORMALIZED_DIR / "airline_caac_sector_monthly.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_caac_sector_proxy_validation.csv"
SUMMARY_OUTPUT_PATH = NORMALIZED_DIR / "airline_caac_sector_proxy_validation_summary.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "airline_code",
    "target_year",
    "period",
    "period_end_month",
    "company_passenger_yoy_pct",
    "caac_passenger_volume_yoy_pct",
    "passenger_growth_error_pp",
    "company_cargo_tonnes_yoy_pct",
    "caac_cargo_mail_volume_yoy_pct",
    "cargo_growth_error_pp",
    "company_ask_yoy_pct",
    "company_rpk_yoy_pct",
    "company_operating_observations",
    "company_observed_only",
    "company_latest_announcement_date",
    "caac_source_release_date",
    "caac_point_in_time_status",
    "validation_status",
    "source_quality",
    "source_note",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior in (None, 0):
        return None
    return 100.0 * current / prior - 100.0


def _period_months(year: int, period: str) -> list[str]:
    end = 6 if period == "H1" else 12
    return [f"{year}-{month:02d}" for month in range(1, end + 1)]


def _company_period_metric(
    operating: pd.DataFrame,
    *,
    airline_code: str,
    year: int,
    period: str,
    metric: str,
) -> tuple[float | None, int, str | None, bool]:
    months = _period_months(year, period)
    rows = operating.loc[
        operating["airline_code"].astype(str).str.zfill(6).eq(str(airline_code).zfill(6))
        & operating["scope"].eq("company_total")
        & operating["metric"].eq(metric)
        & operating["month"].astype(str).isin(months)
    ].copy()
    if rows.empty:
        return None, 0, None, False
    rows["value_numeric"] = pd.to_numeric(rows["value"], errors="coerce")
    rows = rows.loc[rows["value_numeric"].notna()]
    if rows.empty:
        return None, 0, None, False
    observed_only = rows.get("observation_status", pd.Series("observed", index=rows.index)).astype(str).eq("observed").all()
    total = float(rows["value_numeric"].sum())
    latest_announcement = pd.to_datetime(rows.get("announcement_date"), errors="coerce").max()
    latest = latest_announcement.strftime("%Y-%m-%d") if pd.notna(latest_announcement) else None
    return total, int(len(rows)), latest, bool(observed_only)


def _caac_ytd_metric(
    caac: pd.DataFrame,
    *,
    year: int,
    period: str,
    metric: str,
) -> tuple[float | None, str | None, str | None]:
    observation_month = f"{year}-06" if period == "H1" else f"{year}-12"
    rows = caac.loc[
        caac["observation_month"].eq(observation_month)
        & caac["period_type"].eq("ytd")
        & caac["scope"].eq("total")
        & caac["metric"].eq(metric)
    ].copy()
    if rows.empty:
        return None, None, None
    row = rows.sort_values("source_release_date").iloc[-1]
    return _num(row.get("yoy_pct")), str(row.get("source_release_date")), str(row.get("point_in_time_status"))


def build_airline_caac_sector_proxy_validation(
    *,
    operating: pd.DataFrame | None = None,
    caac: pd.DataFrame | None = None,
    years: range | list[int] | tuple[int, ...] = tuple(range(2020, 2027)),
    periods: tuple[str, ...] = ("H1", "FY"),
    retrieved_at: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    operating = operating if operating is not None else pd.read_parquet(OPERATING_PATH)
    caac = caac if caac is not None else pd.read_csv(CAAC_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for year in years:
        for period in periods:
            end_month = f"{year}-06" if period == "H1" else f"{year}-12"
            caac_passenger, caac_release, caac_status = _caac_ytd_metric(
                caac, year=year, period=period, metric="passenger_volume"
            )
            caac_cargo, cargo_release, _ = _caac_ytd_metric(
                caac, year=year, period=period, metric="cargo_mail_volume"
            )
            if caac_release is None and cargo_release is not None:
                caac_release = cargo_release
            for company, airline_code in COMPANY_CODES.items():
                current: dict[str, tuple[float | None, int, str | None, bool]] = {}
                prior: dict[str, tuple[float | None, int, str | None, bool]] = {}
                for metric in ("passengers", "cargo_tonnes", "ask", "rpk"):
                    current[metric] = _company_period_metric(
                        operating, airline_code=airline_code, year=year, period=period, metric=metric
                    )
                    prior[metric] = _company_period_metric(
                        operating, airline_code=airline_code, year=year - 1, period=period, metric=metric
                    )
                company_passenger = _growth(current["passengers"][0], prior["passengers"][0])
                company_cargo = _growth(current["cargo_tonnes"][0], prior["cargo_tonnes"][0])
                passenger_error = (
                    company_passenger - caac_passenger
                    if company_passenger is not None and caac_passenger is not None
                    else None
                )
                cargo_error = (
                    company_cargo - caac_cargo
                    if company_cargo is not None and caac_cargo is not None
                    else None
                )
                observation_count = sum(item[1] for item in current.values())
                observed_only = all(item[3] for item in current.values() if item[1] > 0)
                latest_dates = [item[2] for item in current.values() if item[2]]
                latest_announcement = max(latest_dates) if latest_dates else None
                status = "available_observed_company_and_caac" if passenger_error is not None and cargo_error is not None else "partial_proxy_validation_coverage"
                rows.append(
                    {
                        "dataset_id": "airline_caac_sector_proxy_validation",
                        "company": company,
                        "airline_code": airline_code,
                        "target_year": year,
                        "period": period,
                        "period_end_month": end_month,
                        "company_passenger_yoy_pct": company_passenger,
                        "caac_passenger_volume_yoy_pct": caac_passenger,
                        "passenger_growth_error_pp": passenger_error,
                        "company_cargo_tonnes_yoy_pct": company_cargo,
                        "caac_cargo_mail_volume_yoy_pct": caac_cargo,
                        "cargo_growth_error_pp": cargo_error,
                        "company_ask_yoy_pct": _growth(current["ask"][0], prior["ask"][0]),
                        "company_rpk_yoy_pct": _growth(current["rpk"][0], prior["rpk"][0]),
                        "company_operating_observations": observation_count,
                        "company_observed_only": observed_only,
                        "company_latest_announcement_date": latest_announcement,
                        "caac_source_release_date": caac_release,
                        "caac_point_in_time_status": caac_status,
                        "validation_status": status,
                        "source_quality": "derived_primary_issuer_operating_plus_caac_primary",
                        "source_note": "Proxy validation only: CAAC sector volume is compared with same-window issuer company operating totals; it is not treated as company revenue or yield.",
                        "retrieved_at": retrieved,
                    }
                )
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    summaries: list[dict[str, object]] = []
    for (year, period), group in result.groupby(["target_year", "period"], sort=True):
        passenger_errors = pd.to_numeric(group["passenger_growth_error_pp"], errors="coerce").dropna()
        cargo_errors = pd.to_numeric(group["cargo_growth_error_pp"], errors="coerce").dropna()
        def _corr(a: pd.Series, b: pd.Series) -> float | None:
            pair = pd.concat([a, b], axis=1).dropna()
            if len(pair) < 3 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
                return None
            return float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
        summaries.append(
            {
                "dataset_id": "airline_caac_sector_proxy_validation_summary",
                "target_year": year,
                "period": period,
                "company_observations": int(len(group)),
                "passenger_validation_n": int(len(passenger_errors)),
                "passenger_mae_pp": float(passenger_errors.abs().mean()) if not passenger_errors.empty else None,
                "passenger_median_abs_error_pp": float(passenger_errors.abs().median()) if not passenger_errors.empty else None,
                "passenger_error_p25_pp": float(passenger_errors.quantile(0.25)) if not passenger_errors.empty else None,
                "passenger_error_p75_pp": float(passenger_errors.quantile(0.75)) if not passenger_errors.empty else None,
                "passenger_corr": _corr(group["company_passenger_yoy_pct"], group["caac_passenger_volume_yoy_pct"]),
                "cargo_validation_n": int(len(cargo_errors)),
                "cargo_mae_pp": float(cargo_errors.abs().mean()) if not cargo_errors.empty else None,
                "cargo_median_abs_error_pp": float(cargo_errors.abs().median()) if not cargo_errors.empty else None,
                "cargo_error_p25_pp": float(cargo_errors.quantile(0.25)) if not cargo_errors.empty else None,
                "cargo_error_p75_pp": float(cargo_errors.quantile(0.75)) if not cargo_errors.empty else None,
                "cargo_corr": _corr(group["company_cargo_tonnes_yoy_pct"], group["caac_cargo_mail_volume_yoy_pct"]),
                "source_quality": "derived_primary_issuer_operating_plus_caac_primary",
                "source_note": "MAE and correlation describe sector-to-company operating proxy alignment, not earnings forecast accuracy.",
                "retrieved_at": retrieved,
            }
        )
    summary = pd.DataFrame(summaries)
    result.to_csv(OUTPUT_PATH, index=False)
    summary.to_csv(SUMMARY_OUTPUT_PATH, index=False)
    return result, summary


def fetch_airline_caac_sector_proxy_validation() -> tuple[pd.DataFrame, pd.DataFrame]:
    return build_airline_caac_sector_proxy_validation()


__all__ = [
    "OUTPUT_PATH",
    "SUMMARY_OUTPUT_PATH",
    "build_airline_caac_sector_proxy_validation",
    "fetch_airline_caac_sector_proxy_validation",
]
