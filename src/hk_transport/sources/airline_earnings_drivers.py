"""Comparable airline earnings-driver layer for long/short research.

The underlying issuer tables use different labels and scopes.  This module
does not invent missing values; it selects the best available source metric
for a small canonical KPI catalog and keeps the original metric, unit, page,
source quality and calculation method.  Rows are intentionally long-form so
the same layer can support both a coverage matrix and a company comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


OFFICIAL_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
CATHAY_LEGACY_PATH = NORMALIZED_DIR / "airline_financial_driver_snapshot.csv"
CATHAY_ANNUAL_PATH = NORMALIZED_DIR / "airline_cathay_annual_driver_snapshot.csv"
CATHAY_INTERIM_PATH = NORMALIZED_DIR / "airline_cathay_interim_driver_snapshot.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_earnings_driver_comparability.csv"


@dataclass(frozen=True)
class MetricSpec:
    canonical_metric: str
    definition: str
    analytical_role: str
    value_type: str
    candidates: tuple[str, ...]


METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec("total_revenue", "Reported group or total revenue", "outcome", "monetary", ("total_revenue", "revenue")),
    MetricSpec("passenger_revenue", "Reported passenger-related revenue", "revenue_driver", "monetary", ("passenger_revenue",)),
    MetricSpec("cargo_revenue", "Reported cargo or cargo-and-mail revenue", "revenue_driver", "monetary", ("cargo_revenue",)),
    MetricSpec("operating_cost", "Reported operating cost", "cost_driver", "monetary", ("operating_cost",)),
    MetricSpec("fuel_cost", "Reported gross or accounting aviation-fuel cost", "cost_driver", "monetary", ("fuel_cost",)),
    MetricSpec("fuel_cost_share_pct", "Fuel cost divided by operating cost, or issuer-reported share", "cost_driver", "percentage", ("fuel_cost_share_pct_reported", "fuel_cost_share_pct_derived")),
    MetricSpec("attributable_profit", "Profit attributable to the parent/group shareholders", "outcome", "monetary", ("attributable_net_income", "group_attributable_profit", "net_income_attributable", "profit_total")),
    MetricSpec("operating_cash_flow", "Reported net cash flow from operating activities", "cash_flow_driver", "monetary", ("operating_cash_flow",)),
    MetricSpec("cash_and_cash_equivalents", "Reported group cash and cash equivalents at period end", "liquidity_driver", "monetary", ("cash_and_cash_equivalents",)),
    MetricSpec("total_liabilities", "Reported group total liabilities at period end", "liquidity_driver", "monetary", ("total_liabilities",)),
    MetricSpec("liabilities_to_assets_pct", "Total liabilities divided by total assets; derived from the same issuer report", "liquidity_driver", "percentage", ("liabilities_to_assets_pct_derived",)),
    MetricSpec("interest_bearing_debt", "Reported group interest-bearing debt including stated lease/debt components where the issuer scope is explicit", "liquidity_driver", "monetary", ("interest_bearing_debt",)),
    MetricSpec("capex_cash_paid", "Cash paid for property, plant and equipment and other long-term assets", "cash_flow_driver", "monetary", ("capex_cash_paid",)),
    MetricSpec("net_borrowings", "Issuer-reported net borrowings; not interchangeable with gross interest-bearing debt", "liquidity_driver", "monetary", ("net_borrowings",)),
    MetricSpec("available_unrestricted_liquidity", "Issuer-reported available unrestricted liquidity", "liquidity_driver", "monetary", ("available_unrestricted_liquidity",)),
    MetricSpec("ask", "Available seat kilometres", "capacity_driver", "physical", ("ask",)),
    MetricSpec("rpk", "Revenue passenger kilometres", "demand_driver", "physical", ("rpk", "hkexpress_rpk")),
    MetricSpec("passengers", "Passengers carried or revenue passengers carried", "demand_driver", "physical", ("passengers", "passengers_carried", "passenger_volume")),
    MetricSpec("passenger_load_factor_pct", "Passenger load factor", "demand_driver", "percentage", ("passenger_load_factor_pct", "passenger_load_factor")),
    MetricSpec("passenger_yield", "Passenger revenue yield per RPK", "revenue_driver", "unit_rate", ("passenger_yield", "passenger_yield_derived")),
    MetricSpec("cargo_tonnes", "Cargo tonnes carried", "demand_driver", "physical", ("cargo_tonnes",)),
    MetricSpec("cargo_load_factor_pct", "Cargo/freight load factor", "demand_driver", "percentage", ("cargo_load_factor_pct", "cargo_load_factor")),
    MetricSpec("cargo_yield", "Cargo yield per RTK/freight RTK", "revenue_driver", "unit_rate", ("cargo_yield",)),
    MetricSpec("cask", "Cost per available seat kilometre; issuer-reported where available, otherwise derived", "cost_driver", "unit_rate", ("cask", "cask_derived")),
    MetricSpec("rask_proxy", "Revenue per ASK proxy; source scope is retained because it may be passenger-only", "revenue_driver", "unit_rate", ("rask_derived", "rask_from_reported_yield_derived", "passenger_revenue_per_ask")),
    MetricSpec("fuel_cost_per_ask", "Fuel cost per ASK, derived from fuel cost and ASK", "cost_driver", "unit_rate", ("fuel_cost_per_ask_derived",)),
    MetricSpec("cost_per_atk_ex_fuel", "Cost per ATK excluding fuel", "cost_driver", "unit_rate", ("cost_per_atk_ex_fuel",)),
    MetricSpec("fuel_intensity", "Fuel consumption intensity; ATK/RTK denominator is retained", "cost_driver", "unit_rate", ("fuel_consumption_per_million_atk", "fuel_consumption_per_million_rtk")),
    MetricSpec("fuel_hedging_loss_gain", "Reported fuel-hedging loss/gain; sign convention is source-specific", "risk_driver", "monetary", ("fuel_hedging_loss_gain",)),
    MetricSpec("fuel_hedge_fair_value_change", "Change in fuel-hedge fair value", "risk_driver", "monetary", ("fuel_hedge_fair_value_change",)),
    MetricSpec("fuel_sensitivity_5pct_cost_abs", "Absolute operating-cost sensitivity to a 5% fuel-price move", "risk_driver", "monetary", ("fuel_cost_sensitivity_5pct_cost_abs", "fuel_cost_sensitivity_5pct_abs")),
    MetricSpec("fuel_sensitivity_5pct_profit_up", "Profit sensitivity to a 5% fuel-price increase", "risk_driver", "monetary", ("fuel_price_sensitivity_5pct_profit_if_price_up",)),
    MetricSpec("fuel_sensitivity_5pct_profit_down", "Profit sensitivity to a 5% fuel-price decrease", "risk_driver", "monetary", ("fuel_price_sensitivity_5pct_profit_if_price_down",)),
    MetricSpec("fleet_total", "Reported aircraft fleet total", "capacity_driver", "physical", ("fleet_total", "fleet_total_aircraft")),
    MetricSpec("daily_utilization", "Aircraft daily utilization", "capacity_driver", "unit_rate", ("daily_utilization",)),
)


OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "statement_period", "period_end",
    "information_date", "information_date_available", "cohort", "canonical_metric",
    "metric_definition", "analytical_role", "value_type", "source_metric",
    "value_native", "native_unit", "native_currency", "value_usd", "usd_unit",
    "fx_pair", "fx_observation_date", "metric_scope", "calculation_method",
    "reported_or_derived", "point_in_time_status", "source_quality", "source_url",
    "source_page", "source_note", "retrieved_at",
]


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _load_driver_rows() -> pd.DataFrame:
    """Load the best available issuer driver rows without duplicating Southern."""
    official = pd.read_csv(OFFICIAL_PATH)
    cathay_annual = pd.read_csv(CATHAY_ANNUAL_PATH)
    cathay_interim = pd.read_csv(CATHAY_INTERIM_PATH)
    legacy = pd.read_csv(CATHAY_LEGACY_PATH)
    cathay_legacy = legacy.loc[legacy["company"].eq("Cathay Pacific")].copy()

    frames: list[pd.DataFrame] = []
    mainland = official.loc[~official["company"].eq("Cathay Pacific")].copy()
    mainland["_source_priority"] = 1
    frames.append(mainland)
    for frame in (cathay_annual, cathay_interim):
        frame = frame.copy()
        frame["_source_priority"] = 1
        frames.append(frame)
    cathay_legacy["_source_priority"] = 2
    frames.append(cathay_legacy)

    result = pd.concat(frames, ignore_index=True, sort=False)
    result["information_date"] = result.get("announced_at")
    result["information_date"] = result["information_date"].fillna(
        result["source_note"].astype(str).str.extract(r"announced\s+(\d{4}-\d{2}-\d{2})", expand=False)
    )
    result.loc[result["statement_period"].eq("FY2025") & result["company"].eq("Cathay Pacific"), "information_date"] = "2026-03-11"
    result.loc[result["statement_period"].eq("1H2026") & result["company"].eq("Cathay Pacific"), "information_date"] = "2026-08-05"
    result["information_date"] = result["information_date"].where(result["information_date"].notna(), None)
    return result


def _source_quality_rank(value: Any) -> int:
    return 0 if str(value) == "primary_issuer" else 1


def _is_derived_method(value: Any) -> bool:
    return str(value).strip().lower().startswith("derived")


def _choose_candidate(frame: pd.DataFrame, spec: MetricSpec) -> pd.Series | None:
    candidates = frame.loc[frame["metric"].isin(spec.candidates)].copy()
    if candidates.empty:
        return None
    candidate_rank = {metric: rank for rank, metric in enumerate(spec.candidates)}
    candidates["_metric_rank"] = candidates["metric"].map(candidate_rank).fillna(999)
    candidates["_quality_rank"] = candidates["source_quality"].map(_source_quality_rank)
    candidates["_derived_rank"] = candidates.get("calculation_method", pd.Series(index=candidates.index)).fillna("issuer_reported").map(_is_derived_method).astype(int)
    candidates["_page_rank"] = candidates.get("source_page", pd.Series(index=candidates.index)).isna().astype(int)
    candidates = candidates.sort_values(["_source_priority", "_quality_rank", "_metric_rank", "_derived_rank", "_page_rank"])
    return candidates.iloc[0]


def _cohort(company: str, statement_period: str) -> str | None:
    if statement_period == "FY2025":
        return "common_FY2025"
    if statement_period == "1H2025":
        return "common_1H2025"
    if company == "Cathay Pacific" and statement_period == "1H2026":
        return "latest_available"
    return None


def build_airline_earnings_driver_comparability(
    *, drivers: pd.DataFrame | None = None, retrieved_at: str | None = None
) -> pd.DataFrame:
    """Build a canonical KPI matrix while preserving missing disclosures."""
    drivers = drivers.copy() if drivers is not None else _load_driver_rows()
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    periods = drivers[["company", "ticker", "statement_period", "period_end"]].drop_duplicates()
    for _, period in periods.iterrows():
        period_rows = drivers.loc[
            drivers["company"].eq(period["company"])
            & drivers["statement_period"].eq(period["statement_period"])
        ]
        information_date = period_rows["information_date"].dropna().astype(str).min() if period_rows["information_date"].notna().any() else None
        info_available = information_date is not None
        for spec in METRIC_SPECS:
            selected = _choose_candidate(period_rows, spec)
            if selected is None:
                rows.append({
                    "dataset_id": "airline_earnings_driver_comparability",
                    "company": period["company"], "ticker": period["ticker"],
                    "statement_period": period["statement_period"], "period_end": period["period_end"],
                    "information_date": information_date,
                    "information_date_available": info_available,
                    "cohort": _cohort(str(period["company"]), str(period["statement_period"])),
                    "canonical_metric": spec.canonical_metric,
                    "metric_definition": spec.definition, "analytical_role": spec.analytical_role,
                    "value_type": spec.value_type, "source_metric": None,
                    "value_native": None, "native_unit": None, "native_currency": None,
                    "value_usd": None, "usd_unit": None, "fx_pair": None,
                    "fx_observation_date": None, "metric_scope": None, "calculation_method": None,
                    "reported_or_derived": None,
                    "point_in_time_status": "missing_disclosure" if not info_available else "no_metric_disclosed",
                    "source_quality": None, "source_url": None, "source_page": None,
                    "source_note": "No safe source metric found in the covered report layer; blank is intentional.",
                    "retrieved_at": retrieved,
                })
                continue
            calculation_method = selected.get("calculation_method") or "issuer_reported"
            rows.append({
                "dataset_id": "airline_earnings_driver_comparability",
                "company": selected.get("company"), "ticker": selected.get("ticker"),
                "statement_period": selected.get("statement_period"), "period_end": selected.get("period_end"),
                "information_date": information_date,
                "information_date_available": info_available,
                "cohort": _cohort(str(selected.get("company")), str(selected.get("statement_period"))),
                "canonical_metric": spec.canonical_metric,
                "metric_definition": spec.definition, "analytical_role": spec.analytical_role,
                "value_type": spec.value_type, "source_metric": selected.get("metric"),
                "value_native": _number(selected.get("value_native")),
                "native_unit": selected.get("native_unit"), "native_currency": selected.get("native_currency"),
                "value_usd": _number(selected.get("value_usd")), "usd_unit": selected.get("usd_unit"),
                "fx_pair": selected.get("fx_pair"), "fx_observation_date": selected.get("fx_observation_date"),
                "metric_scope": selected.get("metric_scope"), "calculation_method": calculation_method,
                "reported_or_derived": "derived" if _is_derived_method(calculation_method) else "issuer_reported",
                "point_in_time_status": "point_in_time_ready" if info_available else "period_evidence_without_announcement_date",
                "source_quality": selected.get("source_quality"), "source_url": selected.get("source_url"),
                "source_page": selected.get("source_page"), "source_note": selected.get("source_note"),
                "retrieved_at": retrieved,
            })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_earnings_driver_comparability() -> pd.DataFrame:
    result = build_airline_earnings_driver_comparability()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
