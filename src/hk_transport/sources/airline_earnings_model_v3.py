"""Airline earnings model v3 with an explicit external cargo-demand overlay.

The existing company forecast bridge is a useful unit-economics scaffold, but
its non-passenger line can fall back to a neutral assumption when issuer cargo
tonnage is unavailable.  This module keeps that bridge intact and adds a
separate v3 calculation:

``passenger revenue``
    Existing passenger RASK proxy times forecast ASK.
``cargo/other revenue``
    FY2025 disclosed non-passenger residual grown by a dated, broad China
    goods-trade signal.  The signal is an external demand proxy, not an
    airline cargo-revenue forecast.
``operating profit``
    v3 revenue less the existing aggregate CASK/cost bridge.
``net profit``
    Forecast operating contribution plus the FY2025 reported
    below-operating-to-attributable residual where the official report layer
    has a complete anchor. FY2025 disclosed waterfall rows are carried beside
    the forecast for auditability, but forward finance cost, FX, tax,
    associates and NCI are not yet separately forecast. The old
    net-to-operating ratio is retained only as a fallback for legacy/test
    inputs.

The output is intentionally direction-neutral and scenario-based.  It is a
research calibration layer, not issuer guidance or a trade recommendation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR
from .airline_company_financial_forecast import (
    OUTPUT_PATH as V2_COMPANY_FORECAST_PATH,
    build_airline_company_financial_forecast_bridge,
)


CARGO_PATH = NORMALIZED_DIR / "airline_cargo_demand_proxies.csv"
POSTAL_PATH = NORMALIZED_DIR / "airline_postal_demand_proxies.csv"
TRAVEL_DEMAND_PATH = NORMALIZED_DIR / "airline_travel_demand_events.csv"
AIRPORT_TRAFFIC_PATH = NORMALIZED_DIR / "airline_airport_traffic.csv"
CAAC_PATH = NORMALIZED_DIR / "airline_caac_sector_monthly.csv"
CAAC_ROUTE_LICENCE_PATH = NORMALIZED_DIR / "airline_caac_route_licence_events.csv"
OFFICIAL_DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
HSR_COVERAGE_PATH = NORMALIZED_DIR / "airline_hsr_research_coverage.csv"
FUEL_MATRIX_PATH = NORMALIZED_DIR / "airline_fuel_pass_through_hedge_matrix.csv"
FUEL_RECOVERY_PATH = NORMALIZED_DIR / "airline_fuel_surcharge_recovery.csv"
CARGO_AIRPORT_BRIDGE_PATH = NORMALIZED_DIR / "airline_cargo_airport_bridge.csv"
CARGO_YIELD_BRIDGE_PATH = NORMALIZED_DIR / "airline_cargo_yield_bridge.csv"
FORWARD_ASSUMPTIONS_PATH = NORMALIZED_DIR / "airline_forward_assumptions.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_earnings_model_v3.csv"
COVERAGE_OUTPUT_PATH = NORMALIZED_DIR / "airline_earnings_model_v3_kpi_coverage.csv"

SCENARIO_CARGO_SHOCK = {"bear": -5.0, "base": 0.0, "bull": 5.0}
TRAILING_MONTHS = 3


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _latest_trade_signal(
    cargo: pd.DataFrame,
    *,
    as_of_date: str | None = None,
    trailing_months: int = TRAILING_MONTHS,
) -> dict[str, object]:
    """Summarize the latest available trade snapshot without time travel."""
    required = {
        "observation_month",
        "export_yoy_pct",
        "import_yoy_pct",
        "total_trade_yoy_pct",
        "source_snapshot_date",
    }
    if cargo.empty or not required.issubset(cargo.columns):
        return {
            "cargo_proxy_status": "missing_external_trade_proxy",
            "cargo_proxy_method": "not_available",
            "cargo_proxy_yoy_pct": None,
            "cargo_proxy_export_yoy_pct": None,
            "cargo_proxy_import_yoy_pct": None,
            "cargo_proxy_total_trade_yoy_pct": None,
            "cargo_proxy_observation_month_start": None,
            "cargo_proxy_observation_month_end": None,
            "cargo_proxy_source_snapshot_date": None,
            "cargo_proxy_observations": 0,
        }
    rows = cargo.copy()
    rows["observation_month_parsed"] = pd.to_datetime(
        rows["observation_month"].astype(str), format="%Y-%m", errors="coerce"
    )
    rows["source_snapshot_date_parsed"] = pd.to_datetime(
        rows["source_snapshot_date"], errors="coerce"
    )
    cutoff = pd.to_datetime(as_of_date, errors="coerce") if as_of_date else pd.NaT
    if pd.notna(cutoff):
        # MOFCOM exposes a retrieval snapshot rather than an original release
        # timestamp.  The retrieval date is therefore the conservative PIT
        # boundary; never use a later snapshot for an earlier model date.
        rows = rows.loc[
            rows["observation_month_parsed"].le(cutoff)
            & rows["source_snapshot_date_parsed"].le(cutoff)
        ]
    rows = rows.dropna(subset=["observation_month_parsed"])
    if rows.empty:
        return {
            "cargo_proxy_status": "no_observation_before_cutoff",
            "cargo_proxy_method": "not_available_before_cutoff",
            "cargo_proxy_yoy_pct": None,
            "cargo_proxy_export_yoy_pct": None,
            "cargo_proxy_import_yoy_pct": None,
            "cargo_proxy_total_trade_yoy_pct": None,
            "cargo_proxy_observation_month_start": None,
            "cargo_proxy_observation_month_end": None,
            "cargo_proxy_source_snapshot_date": None,
            "cargo_proxy_observations": 0,
        }
    # Latest retrieval vintage only: this prevents a mixed-vintage average if
    # multiple daily captures have accumulated in the local history.
    latest_snapshot = rows["source_snapshot_date_parsed"].max()
    if pd.notna(latest_snapshot):
        rows = rows.loc[rows["source_snapshot_date_parsed"].eq(latest_snapshot)]
    rows = rows.sort_values("observation_month_parsed").tail(max(1, trailing_months))
    export = pd.to_numeric(rows["export_yoy_pct"], errors="coerce")
    imports = pd.to_numeric(rows["import_yoy_pct"], errors="coerce")
    total = pd.to_numeric(rows["total_trade_yoy_pct"], errors="coerce")
    # Exports are a slightly larger weight because outbound manufactured-goods
    # flows are the closest broad proxy to air-cargo demand; imports remain a
    # useful belly-cargo/industrial-cycle cross-check.
    cargo_signal = (0.6 * export + 0.4 * imports).mean()
    return {
        "cargo_proxy_status": "available_external_trade_proxy",
        "cargo_proxy_method": "0.6_latest_export_yoy_plus_0.4_latest_import_yoy_trailing_mean",
        "cargo_proxy_yoy_pct": float(cargo_signal) if pd.notna(cargo_signal) else None,
        "cargo_proxy_export_yoy_pct": float(export.mean()) if export.notna().any() else None,
        "cargo_proxy_import_yoy_pct": float(imports.mean()) if imports.notna().any() else None,
        "cargo_proxy_total_trade_yoy_pct": float(total.mean()) if total.notna().any() else None,
        "cargo_proxy_observation_month_start": rows["observation_month_parsed"].min().strftime("%Y-%m"),
        "cargo_proxy_observation_month_end": rows["observation_month_parsed"].max().strftime("%Y-%m"),
        "cargo_proxy_source_snapshot_date": latest_snapshot.strftime("%Y-%m-%d") if pd.notna(latest_snapshot) else None,
        "cargo_proxy_observations": int(len(rows)),
    }


def _latest_caac_sector_signal(
    caac: pd.DataFrame,
    *,
    as_of_date: str | None = None,
) -> dict[str, object]:
    """Return release-date-safe latest total monthly CAAC context."""
    required = {
        "observation_month",
        "period_type",
        "scope",
        "metric",
        "value",
        "yoy_pct",
        "source_release_date",
    }
    if caac.empty or not required.issubset(caac.columns):
        return {
            "caac_sector_context_status": "missing_caac_sector_context",
            "caac_sector_observation_month": None,
            "caac_sector_source_release_date": None,
            "caac_sector_passenger_yoy_pct": None,
            "caac_sector_cargo_yoy_pct": None,
            "caac_sector_load_factor_pct": None,
            "caac_sector_utilization_hours": None,
        }
    rows = caac.loc[
        caac["period_type"].eq("monthly") & caac["scope"].eq("total")
    ].copy()
    rows["observation_month_parsed"] = pd.to_datetime(
        rows["observation_month"].astype(str), format="%Y-%m", errors="coerce"
    )
    rows["source_release_date_parsed"] = pd.to_datetime(
        rows["source_release_date"], errors="coerce"
    )
    cutoff = pd.to_datetime(as_of_date, errors="coerce") if as_of_date else pd.NaT
    if pd.notna(cutoff):
        rows = rows.loc[
            rows["observation_month_parsed"].le(cutoff)
            & rows["source_release_date_parsed"].le(cutoff)
        ]
    if rows.empty:
        return {
            "caac_sector_context_status": "no_caac_observation_before_cutoff",
            "caac_sector_observation_month": None,
            "caac_sector_source_release_date": None,
            "caac_sector_passenger_yoy_pct": None,
            "caac_sector_cargo_yoy_pct": None,
            "caac_sector_load_factor_pct": None,
            "caac_sector_utilization_hours": None,
        }
    latest_month = rows["observation_month_parsed"].max()
    rows = rows.loc[rows["observation_month_parsed"].eq(latest_month)]
    value_by_metric = rows.set_index("metric")["value"].to_dict()
    yoy_by_metric = rows.set_index("metric")["yoy_pct"].to_dict()
    release = rows["source_release_date_parsed"].max()
    return {
        "caac_sector_context_status": "available_release_date_safe_monthly_context",
        "caac_sector_observation_month": latest_month.strftime("%Y-%m"),
        "caac_sector_source_release_date": release.strftime("%Y-%m-%d") if pd.notna(release) else None,
        "caac_sector_passenger_yoy_pct": _num(yoy_by_metric.get("passenger_volume")),
        "caac_sector_cargo_yoy_pct": _num(yoy_by_metric.get("cargo_mail_volume")),
        "caac_sector_load_factor_pct": _num(value_by_metric.get("scheduled_passenger_load_factor")),
        "caac_sector_utilization_hours": _num(value_by_metric.get("aircraft_daily_utilization")),
    }


def _latest_postal_sector_signal(
    postal: pd.DataFrame,
    *,
    as_of_date: str | None = None,
) -> dict[str, object]:
    """Return release-date-safe national postal/express demand context.

    SPB parcel data is a broad logistics/e-commerce proxy, not airline cargo
    revenue.  The cutoff is applied to the article release date, so a model
    dated 2026-06-30 cannot use the 2026 H1 article released in July.
    """
    default = {
        "postal_context_status": "missing_postal_demand_context",
        "postal_observation_period": None,
        "postal_observation_month": None,
        "postal_source_release_date": None,
        "postal_express_revenue_yoy_pct": None,
        "postal_express_volume_yoy_pct": None,
        "postal_postal_volume_yoy_pct": None,
        "postal_inter_city_volume_yoy_pct": None,
        "postal_international_volume_yoy_pct": None,
        "postal_source_quality": None,
    }
    required = {
        "observation_period",
        "period_type",
        "observation_month",
        "period_end",
        "metric",
        "yoy_pct",
        "source_release_date",
        "source_quality",
    }
    if postal.empty or not required.issubset(postal.columns):
        return default
    rows = postal.loc[postal["period_type"].eq("cumulative")].copy()
    rows["period_end_parsed"] = pd.to_datetime(rows["period_end"], errors="coerce")
    rows["source_release_date_parsed"] = pd.to_datetime(
        rows["source_release_date"], errors="coerce"
    )
    rows = rows.dropna(subset=["period_end_parsed", "source_release_date_parsed"])
    cutoff = pd.to_datetime(as_of_date, errors="coerce") if as_of_date else pd.NaT
    if pd.notna(cutoff):
        rows = rows.loc[
            rows["period_end_parsed"].le(cutoff)
            & rows["source_release_date_parsed"].le(cutoff)
        ]
    if rows.empty:
        result = default.copy()
        result["postal_context_status"] = "no_postal_observation_before_cutoff"
        return result
    latest_period_end = rows["period_end_parsed"].max()
    rows = rows.loc[rows["period_end_parsed"].eq(latest_period_end)]
    yoy = rows.set_index("metric")["yoy_pct"].to_dict()
    release = rows["source_release_date_parsed"].max()
    result = {
        "postal_context_status": "available_release_date_safe_cumulative_context",
        "postal_observation_period": rows["observation_period"].iloc[0],
        "postal_observation_month": rows["observation_month"].iloc[0],
        "postal_source_release_date": release.strftime("%Y-%m-%d"),
        "postal_express_revenue_yoy_pct": _num(yoy.get("express_business_revenue")),
        "postal_express_volume_yoy_pct": _num(yoy.get("express_delivery_volume")),
        "postal_postal_volume_yoy_pct": _num(yoy.get("postal_delivery_volume")),
        "postal_inter_city_volume_yoy_pct": _num(yoy.get("express_inter_city_volume")),
        "postal_international_volume_yoy_pct": _num(
            yoy.get("express_international_hk_macao_taiwan_volume")
        ),
        "postal_source_quality": rows["source_quality"].iloc[0],
    }
    return result


def _latest_travel_demand_signal(
    travel_events: pd.DataFrame,
    *,
    as_of_date: str | None = None,
) -> dict[str, object]:
    """Return release-date-safe MOT/MCT holiday demand context.

    Holiday observations are intentionally context-only.  The helper selects
    the latest admissible event for each metric, keeps the event duration and
    does not turn sparse holiday points into a monthly airline demand series.
    """
    default = {
        "travel_demand_context_status": "missing_travel_demand_event_context",
        "travel_demand_event_count_before_cutoff": 0,
        "travel_demand_latest_event_id": None,
        "travel_demand_latest_event_name": None,
        "travel_demand_latest_event_family": None,
        "travel_demand_latest_source_release_date": None,
        "travel_demand_latest_duration_days": None,
        "travel_demand_domestic_tourism_yoy_pct": None,
        "travel_demand_domestic_tourism_daily_yoy_pct": None,
        "travel_demand_domestic_tourism_spend_yoy_pct": None,
        "travel_demand_domestic_tourism_spend_daily_yoy_pct": None,
        "travel_demand_civil_aviation_passengers_mn_per_day": None,
        "travel_demand_rail_passengers_mn_per_day": None,
        "travel_demand_total_flow_yoy_pct": None,
        "travel_demand_source_quality": None,
    }
    required = {
        "event_id",
        "event_family",
        "event_name",
        "event_duration_days",
        "metric",
        "value_per_day",
        "yoy_pct",
        "daily_yoy_pct",
        "source_release_date",
        "source_quality",
    }
    if travel_events.empty or not required.issubset(travel_events.columns):
        return default
    rows = travel_events.copy()
    rows["source_release_date_parsed"] = pd.to_datetime(
        rows["source_release_date"], errors="coerce"
    )
    rows = rows.dropna(subset=["source_release_date_parsed"])
    cutoff = pd.to_datetime(as_of_date, errors="coerce") if as_of_date else pd.NaT
    if pd.notna(cutoff):
        rows = rows.loc[rows["source_release_date_parsed"].le(cutoff)]
    if rows.empty:
        result = default.copy()
        result["travel_demand_context_status"] = "no_travel_demand_event_before_cutoff"
        return result
    rows = rows.sort_values("source_release_date_parsed")
    latest_event = rows.iloc[-1]

    def latest_metric(metric: str) -> pd.Series | None:
        selected = rows.loc[rows["metric"].eq(metric)]
        return selected.iloc[-1] if not selected.empty else None

    tourism = latest_metric("domestic_travelers")
    tourism_spend = latest_metric("domestic_tourism_spend")
    civil = latest_metric("civil_aviation_passengers")
    rail = latest_metric("rail_passengers")
    total_flow = latest_metric("cross_regional_person_flow")
    return {
        "travel_demand_context_status": "available_release_date_safe_event_context",
        "travel_demand_event_count_before_cutoff": int(rows["event_id"].nunique()),
        "travel_demand_latest_event_id": latest_event.get("event_id"),
        "travel_demand_latest_event_name": latest_event.get("event_name"),
        "travel_demand_latest_event_family": latest_event.get("event_family"),
        "travel_demand_latest_source_release_date": latest_event["source_release_date_parsed"].strftime("%Y-%m-%d"),
        "travel_demand_latest_duration_days": _num(latest_event.get("event_duration_days")),
        "travel_demand_domestic_tourism_yoy_pct": _num(tourism.get("yoy_pct")) if tourism is not None else None,
        "travel_demand_domestic_tourism_daily_yoy_pct": _num(tourism.get("daily_yoy_pct")) if tourism is not None else None,
        "travel_demand_domestic_tourism_spend_yoy_pct": _num(tourism_spend.get("yoy_pct")) if tourism_spend is not None else None,
        "travel_demand_domestic_tourism_spend_daily_yoy_pct": _num(tourism_spend.get("daily_yoy_pct")) if tourism_spend is not None else None,
        "travel_demand_civil_aviation_passengers_mn_per_day": _num(civil.get("value_per_day")) if civil is not None else None,
        "travel_demand_rail_passengers_mn_per_day": _num(rail.get("value_per_day")) if rail is not None else None,
        "travel_demand_total_flow_yoy_pct": _num(total_flow.get("yoy_pct")) if total_flow is not None else None,
        "travel_demand_source_quality": latest_event.get("source_quality"),
    }


def _latest_airport_traffic_signal(
    airport_traffic: pd.DataFrame,
    *,
    as_of_date: str | None = None,
) -> dict[str, object]:
    """Return release-date-safe airport hub demand context.

    The signal keeps each airport's latest admissible total observation and
    does not blend airports into a single index.  It is sector context only
    and is never multiplied into company revenue.
    """
    default: dict[str, object] = {
        "airport_traffic_context_status": "missing_airport_traffic_context",
        "airport_traffic_observation_month": None,
        "airport_traffic_source_release_date": None,
        "airport_traffic_airports_available": 0,
        "airport_traffic_passenger_throughput_10k_persons": None,
        "airport_traffic_passenger_yoy_pct": None,
        "airport_traffic_aircraft_movements": None,
        "airport_traffic_movements_yoy_pct": None,
        "airport_traffic_cargo_10k_tonnes": None,
        "airport_traffic_cargo_yoy_pct": None,
        "airport_traffic_airport": None,
        "airport_traffic_source_quality": None,
    }
    required = {
        "observation_month",
        "airport",
        "metric",
        "scope",
        "value",
        "yoy_pct",
        "source_release_date",
        "source_quality",
    }
    if airport_traffic.empty or not required.issubset(airport_traffic.columns):
        return default
    rows = airport_traffic.loc[airport_traffic["scope"].eq("total")].copy()
    rows["observation_month_parsed"] = pd.to_datetime(
        rows["observation_month"].astype(str), format="%Y-%m", errors="coerce"
    )
    rows["source_release_date_parsed"] = pd.to_datetime(
        rows["source_release_date"], errors="coerce"
    )
    rows = rows.dropna(subset=["observation_month_parsed", "source_release_date_parsed"])
    cutoff = pd.to_datetime(as_of_date, errors="coerce") if as_of_date else pd.NaT
    if pd.notna(cutoff):
        rows = rows.loc[
            rows["observation_month_parsed"].le(cutoff)
            & rows["source_release_date_parsed"].le(cutoff)
        ]
    if rows.empty:
        result = default.copy()
        result["airport_traffic_context_status"] = "no_airport_traffic_before_cutoff"
        return result
    latest_month = rows["observation_month_parsed"].max()
    rows = rows.loc[rows["observation_month_parsed"].eq(latest_month)]
    airports = sorted(rows["airport"].dropna().unique())
    release = rows["source_release_date_parsed"].max()
    passengers = rows.loc[rows["metric"].eq("passenger_throughput")]
    movements = rows.loc[rows["metric"].eq("aircraft_movements")]
    cargo = rows.loc[rows["metric"].eq("cargo_throughput")]

    def _total_value(selected: pd.DataFrame) -> tuple[float | None, float | None]:
        if selected.empty:
            return None, None
        value = pd.to_numeric(selected["value"], errors="coerce").sum(min_count=1)
        yoy = pd.to_numeric(selected["yoy_pct"], errors="coerce").mean()
        return (None if pd.isna(value) else float(value), None if pd.isna(yoy) else float(yoy))

    passenger_value, passenger_yoy = _total_value(passengers)
    movements_value, movements_yoy = _total_value(movements)
    cargo_value, cargo_yoy = _total_value(cargo)
    return {
        "airport_traffic_context_status": "available_release_date_safe_hub_context",
        "airport_traffic_observation_month": latest_month.strftime("%Y-%m"),
        "airport_traffic_source_release_date": release.strftime("%Y-%m-%d"),
        "airport_traffic_airports_available": int(len(airports)),
        "airport_traffic_passenger_throughput_10k_persons": passenger_value,
        "airport_traffic_passenger_yoy_pct": passenger_yoy,
        "airport_traffic_aircraft_movements": movements_value,
        "airport_traffic_movements_yoy_pct": movements_yoy,
        "airport_traffic_cargo_10k_tonnes": cargo_value,
        "airport_traffic_cargo_yoy_pct": cargo_yoy,
        "airport_traffic_airport": ",".join(airports),
        "airport_traffic_source_quality": rows["source_quality"].iloc[0],
    }


def _blended_cargo_demand_signal(
    trade_signal: dict[str, object],
    caac_signal: dict[str, object],
    postal_signal: dict[str, object],
) -> dict[str, object]:
    """Triangulate cargo demand without pretending proxies are airline revenue.

    CAAC cargo/mail growth is the closest direct sector measure, MOFCOM trade
    growth is a leading merchandise-cycle measure, and SPB express-volume
    growth captures e-commerce/time-sensitive logistics.  We use fixed,
    pre-declared weights and renormalize only when a component is unavailable:
    40% CAAC, 40% MOFCOM and 20% SPB.  The component values remain in the
    output for audit and future backtesting.
    """
    components = {
        "caac_cargo_mail_yoy_pct": _num(caac_signal.get("caac_sector_cargo_yoy_pct")),
        "mofcom_trade_yoy_pct": _num(trade_signal.get("cargo_proxy_yoy_pct")),
        "spb_express_volume_yoy_pct": _num(postal_signal.get("postal_express_volume_yoy_pct")),
    }
    weights = {
        "caac_cargo_mail_yoy_pct": 0.40,
        "mofcom_trade_yoy_pct": 0.40,
        "spb_express_volume_yoy_pct": 0.20,
    }
    available = {key: value for key, value in components.items() if value is not None}
    if not available:
        return {
            "cargo_demand_blend_status": "missing_cargo_demand_components",
            "cargo_proxy_blended_yoy_pct": None,
            "cargo_proxy_blended_method": "not_available",
            "cargo_proxy_blended_components": "",
        }
    weight_total = sum(weights[key] for key in available)
    blended = sum(available[key] * weights[key] for key in available) / weight_total
    method = ";".join(
        f"{key}={weights[key] / weight_total:.2f}" for key in available
    )
    component_text = ";".join(f"{key}={value:.4f}" for key, value in available.items())
    status = (
        "available_three_source_cargo_demand_blend"
        if len(available) == 3
        else "available_partial_cargo_demand_blend"
    )
    return {
        "cargo_demand_blend_status": status,
        "cargo_proxy_blended_yoy_pct": float(blended),
        "cargo_proxy_blended_method": f"fixed_weights_renormalized:{method}",
        "cargo_proxy_blended_components": component_text,
    }


def _company_hsr_context(
    hsr_coverage: pd.DataFrame,
    company: str,
) -> dict[str, object]:
    """Return route/HSR coverage context without forcing a revenue impact."""
    default = {
        "hsr_context_status": "missing_hsr_coverage",
        "hsr_candidate_route_count": None,
        "hsr_query_leg_count": None,
        "hsr_verified_observation_count": None,
        "hsr_ask_weighted_leg_count": None,
        "hsr_substitution_score_available": None,
        "hsr_coverage_status": None,
        "hsr_snapshot_as_of_date": None,
    }
    required = {
        "company",
        "candidate_route_count",
        "query_leg_count",
        "verified_observation_count",
        "ask_weighted_leg_count",
        "hsr_substitution_score_available",
        "coverage_status",
        "snapshot_as_of_date",
    }
    if hsr_coverage.empty or not required.issubset(hsr_coverage.columns):
        return default
    rows = hsr_coverage.loc[hsr_coverage["company"].eq(company)].copy()
    if rows.empty:
        return default
    rows["snapshot_parsed"] = pd.to_datetime(rows["snapshot_as_of_date"], errors="coerce")
    row = rows.sort_values("snapshot_parsed").iloc[-1]
    return {
        "hsr_context_status": "available_route_coverage_context_only",
        "hsr_candidate_route_count": _num(row.get("candidate_route_count")),
        "hsr_query_leg_count": _num(row.get("query_leg_count")),
        "hsr_verified_observation_count": _num(row.get("verified_observation_count")),
        "hsr_ask_weighted_leg_count": _num(row.get("ask_weighted_leg_count")),
        "hsr_substitution_score_available": _num(row.get("hsr_substitution_score_available")),
        "hsr_coverage_status": row.get("coverage_status"),
        "hsr_snapshot_as_of_date": row.get("snapshot_as_of_date"),
    }


def _company_caac_route_licence_context(
    route_events: pd.DataFrame,
    company: str,
    *,
    as_of_date: str | None = None,
) -> dict[str, object]:
    """Summarize dated CAAC planned-supply events without converting to ASK."""
    default = {
        "caac_route_licence_context_status": "missing_caac_route_licence_context",
        "caac_route_licence_new_route_count": None,
        "caac_route_licence_new_route_initial_frequency_per_week": None,
        "caac_route_licence_cancellation_count": None,
        "caac_route_licence_source_release_date": None,
        "caac_route_licence_schedule_season": None,
    }
    required = {
        "airline_normalized_name",
        "table_type",
        "initial_frequency_per_week",
        "source_release_date",
        "schedule_season",
    }
    if route_events.empty or not required.issubset(route_events.columns):
        return default
    rows = route_events.loc[route_events["airline_normalized_name"].eq(company)].copy()
    rows["source_release_date_parsed"] = pd.to_datetime(
        rows["source_release_date"], errors="coerce"
    )
    cutoff = pd.to_datetime(as_of_date, errors="coerce") if as_of_date else pd.NaT
    if pd.notna(cutoff):
        rows = rows.loc[rows["source_release_date_parsed"].le(cutoff)]
    if rows.empty:
        result = default.copy()
        result["caac_route_licence_context_status"] = "no_caac_route_licence_before_cutoff"
        return result
    additions = rows.loc[rows["table_type"].eq("new_domestic_route")]
    cancellations = rows.loc[rows["table_type"].eq("cancelled_route_licence")]
    release = rows["source_release_date_parsed"].max()
    return {
        "caac_route_licence_context_status": "available_planned_supply_context_only",
        "caac_route_licence_new_route_count": int(len(additions)),
        "caac_route_licence_new_route_initial_frequency_per_week": float(
            pd.to_numeric(additions["initial_frequency_per_week"], errors="coerce").sum(min_count=1)
        ) if not additions.empty else 0.0,
        "caac_route_licence_cancellation_count": int(len(cancellations)),
        "caac_route_licence_source_release_date": release.strftime("%Y-%m-%d") if pd.notna(release) else None,
        "caac_route_licence_schedule_season": rows["schedule_season"].iloc[0],
    }


def _company_fuel_context(
    fuel_matrix: pd.DataFrame,
    company: str,
) -> dict[str, object]:
    """Return disclosed hedge/pass-through context and keep it non-zero-safe."""
    default = {
        "fuel_context_status": "missing_fuel_hedge_pass_through_matrix",
        "fuel_hedge_status": None,
        "numeric_hedge_anchor_available": None,
        "hedge_notional_native": None,
        "hedge_fair_value_change_native": None,
        "hedge_fair_value_end_native": None,
        "fuel_pass_through_status": None,
        "fuel_surcharge_gt800_current_cny": None,
        "fuel_surcharge_upto800_current_cny": None,
        "fuel_surcharge_effective_from": None,
        "fuel_matrix_statement_period": None,
    }
    required = {
        "company",
        "statement_period",
        "hedge_status",
        "numeric_hedge_anchor_available",
        "pass_through_status",
    }
    if fuel_matrix.empty or not required.issubset(fuel_matrix.columns):
        return default
    rows = fuel_matrix.loc[fuel_matrix["company"].eq(company)].copy()
    if rows.empty:
        return default
    # Prefer FY2025 as the latest complete official comparison period; if it
    # is absent, keep the latest period present rather than imputing a hedge.
    fy = rows.loc[rows["statement_period"].eq("FY2025")]
    row = (fy if not fy.empty else rows).iloc[-1]
    return {
        "fuel_context_status": "available_disclosure_and_policy_context",
        "fuel_hedge_status": row.get("hedge_status"),
        "numeric_hedge_anchor_available": row.get("numeric_hedge_anchor_available"),
        "hedge_notional_native": _num(row.get("hedge_notional_native")),
        "hedge_fair_value_change_native": _num(row.get("hedge_fair_value_change_native")),
        "hedge_fair_value_end_native": _num(row.get("hedge_fair_value_end_native")),
        "fuel_pass_through_status": row.get("pass_through_status"),
        "fuel_surcharge_gt800_current_cny": _num(row.get("surcharge_gt800_current_cny")),
        "fuel_surcharge_upto800_current_cny": _num(row.get("surcharge_upto800_current_cny")),
        "fuel_surcharge_effective_from": row.get("surcharge_effective_from"),
        "fuel_matrix_statement_period": row.get("statement_period"),
    }


def _latest_fuel_surcharge_recovery_context(
    recovery: pd.DataFrame,
) -> dict[str, object]:
    """Carry the latest dated surcharge-to-fuel recovery proxy as context."""
    default: dict[str, object] = {
        "fuel_surcharge_recovery_status": "missing_surcharge_recovery_proxy",
        "fuel_surcharge_recovery_observations": 0,
        "mainland_surcharge_change_pct": None,
        "mainland_fuel_change_pct": None,
        "mainland_surcharge_to_fuel_change_ratio": None,
        "cathay_surcharge_change_pct": None,
        "cathay_fuel_change_pct": None,
        "cathay_surcharge_to_fuel_change_ratio": None,
        "fuel_surcharge_recovery_effective_from": None,
    }
    required = {
        "carrier_scope",
        "effective_from",
        "surcharge_change_pct",
        "fuel_change_pct",
        "surcharge_to_fuel_change_ratio",
    }
    if recovery.empty or not required.issubset(recovery.columns):
        return default
    rows = recovery.copy()
    rows["effective_parsed"] = pd.to_datetime(rows["effective_from"], errors="coerce")
    rows = rows.dropna(subset=["effective_parsed"])
    if rows.empty:
        return default
    latest_date = rows["effective_parsed"].max()

    def first_row(selected: pd.DataFrame) -> dict[str, float | None]:
        if selected.empty:
            return {
                "surcharge_change_pct": None,
                "fuel_change_pct": None,
                "ratio": None,
            }
        return {
            "surcharge_change_pct": _num(selected.iloc[0].get("surcharge_change_pct")),
            "fuel_change_pct": _num(selected.iloc[0].get("fuel_change_pct")),
            "ratio": _num(selected.iloc[0].get("surcharge_to_fuel_change_ratio")),
        }

    # Select the latest admissible observation per carrier scope so an older
    # mainland schedule change is not hidden by a newer Cathay-only row.
    mainland_scope = rows.loc[
        rows["carrier_scope"].str.contains("Mainland", case=False, na=False)
    ]
    cathay_scope = rows.loc[
        rows["carrier_scope"].str.contains("Cathay", case=False, na=False)
    ]
    mainland_row = first_row(
        mainland_scope.loc[
            mainland_scope["effective_parsed"].eq(mainland_scope["effective_parsed"].max())
        ]
        if not mainland_scope.empty
        else mainland_scope
    )
    cathay_row = first_row(
        cathay_scope.loc[
            cathay_scope["effective_parsed"].eq(cathay_scope["effective_parsed"].max())
        ]
        if not cathay_scope.empty
        else cathay_scope
    )
    return {
        "fuel_surcharge_recovery_status": "available_dated_surcharge_to_fuel_recovery_proxy",
        "fuel_surcharge_recovery_observations": int(len(rows)),
        "mainland_surcharge_change_pct": mainland_row["surcharge_change_pct"],
        "mainland_fuel_change_pct": mainland_row["fuel_change_pct"],
        "mainland_surcharge_to_fuel_change_ratio": mainland_row["ratio"],
        "cathay_surcharge_change_pct": cathay_row["surcharge_change_pct"],
        "cathay_fuel_change_pct": cathay_row["fuel_change_pct"],
        "cathay_surcharge_to_fuel_change_ratio": cathay_row["ratio"],
        "fuel_surcharge_recovery_effective_from": latest_date.strftime("%Y-%m-%d"),
    }


def _company_cargo_airport_bridge_context(
    bridge: pd.DataFrame,
    company: str,
) -> dict[str, object]:
    """Carry the airport-cargo bridge calibration for one company."""
    default: dict[str, object] = {
        "cargo_airport_bridge_status": "missing_cargo_airport_bridge",
        "cargo_airport_hub_airports": None,
        "cargo_airport_tonnes": None,
        "cargo_airport_yoy_pct": None,
        "cargo_company_tonnes": None,
        "cargo_company_tonnes_yoy_pct": None,
        "cargo_tonnage_bridge_gap_pp": None,
        "cargo_airport_as_pct_of_company_tonnage": None,
        "cargo_revenue_per_tonne_native": None,
    }
    if bridge.empty or "company" not in bridge.columns:
        return default
    rows = bridge.loc[bridge["company"].eq(company)]
    if rows.empty:
        result = default.copy()
        result["cargo_airport_bridge_status"] = "no_bridge_row_for_company"
        return result
    row = rows.iloc[0]
    return {
        "cargo_airport_bridge_status": row.get("bridge_status"),
        "cargo_airport_hub_airports": row.get("hub_airports"),
        "cargo_airport_tonnes": _num(row.get("airport_cargo_tonnes")),
        "cargo_airport_yoy_pct": _num(row.get("airport_cargo_yoy_pct")),
        "cargo_company_tonnes": _num(row.get("company_cargo_tonnes")),
        "cargo_company_tonnes_yoy_pct": _num(row.get("company_cargo_tonnes_yoy_pct")),
        "cargo_tonnage_bridge_gap_pp": _num(row.get("cargo_tonnage_bridge_gap_pp")),
        "cargo_airport_as_pct_of_company_tonnage": _num(
            row.get("airport_cargo_as_pct_of_company_cargo")
        ),
        "cargo_revenue_per_tonne_native": _num(
            row.get("reported_cargo_revenue_per_tonne_native")
        ),
    }


def _company_cargo_yield_bridge_context(
    bridge: pd.DataFrame,
    company: str,
) -> dict[str, object]:
    """Carry the forward cargo-revenue bridge for one company."""
    default: dict[str, object] = {
        "cargo_yield_bridge_status": "missing_cargo_yield_bridge",
        "cargo_yield_bridge_revenue_anchor_period": None,
        "cargo_yield_bridge_anchor_revenue_native_mn": None,
        "cargo_yield_bridge_anchor_tonnes": None,
        "cargo_yield_bridge_revenue_per_tonne_native": None,
        "cargo_yield_bridge_h1_2026_tonnes": None,
        "cargo_yield_bridge_h1_2026_tonnes_yoy_pct": None,
        "cargo_yield_bridge_h1_2026_revenue_native_mn": None,
        "cargo_yield_bridge_revenue_growth_pct": None,
        "cargo_yield_bridge_proxy_revenue_native_mn": None,
    }
    if bridge.empty or "company" not in bridge.columns:
        return default
    rows = bridge.loc[bridge["company"].eq(company)]
    if rows.empty:
        result = default.copy()
        result["cargo_yield_bridge_status"] = "no_bridge_row_for_company"
        return result
    row = rows.iloc[0]
    return {
        "cargo_yield_bridge_status": row.get("bridge_status"),
        "cargo_yield_bridge_revenue_anchor_period": row.get("revenue_anchor_period"),
        "cargo_yield_bridge_anchor_revenue_native_mn": _num(
            row.get("h1_2025_cargo_revenue_native_mn")
        ),
        "cargo_yield_bridge_anchor_tonnes": _num(row.get("h1_2025_cargo_tonnes")),
        "cargo_yield_bridge_revenue_per_tonne_native": _num(
            row.get("revenue_per_tonne_native")
        ),
        "cargo_yield_bridge_h1_2026_tonnes": _num(row.get("h1_2026_cargo_tonnes")),
        "cargo_yield_bridge_h1_2026_tonnes_yoy_pct": _num(
            row.get("h1_2026_cargo_tonnes_yoy_pct")
        ),
        "cargo_yield_bridge_h1_2026_revenue_native_mn": _num(
            row.get("h1_2026_cargo_revenue_bridge_native_mn")
        ),
        "cargo_yield_bridge_revenue_growth_pct": _num(
            row.get("bridge_revenue_growth_pct")
        ),
        "cargo_yield_bridge_proxy_revenue_native_mn": _num(
            row.get("h1_2025_cargo_revenue_proxy_native_mn")
        ),
    }


def _company_forward_assumptions_context(
    assumptions: pd.DataFrame,
    company: str,
) -> dict[str, object]:
    """Carry the forward tax-rate and FX assumptions for one company."""
    default: dict[str, object] = {
        "forward_assumptions_status": "missing_forward_assumptions",
        "forward_fy2025_effective_tax_rate_pct": None,
        "forward_tax_assumption_status": None,
        "forward_fx_usd_cny": None,
        "forward_fx_observation_date": None,
        "forward_fx_status": None,
    }
    if assumptions.empty or "company" not in assumptions.columns:
        return default
    rows = assumptions.loc[assumptions["company"].eq(company)]
    if rows.empty:
        result = default.copy()
        result["forward_assumptions_status"] = "no_assumption_row_for_company"
        return result
    row = rows.iloc[0]
    return {
        "forward_assumptions_status": "available_forward_tax_and_fx_assumptions",
        "forward_fy2025_effective_tax_rate_pct": _num(
            row.get("fy2025_effective_tax_rate_pct")
        ),
        "forward_tax_assumption_status": row.get("tax_assumption_status"),
        "forward_fx_usd_cny": _num(row.get("forward_fx_usd_cny")),
        "forward_fx_observation_date": row.get("forward_fx_observation_date"),
        "forward_fx_status": row.get("forward_fx_status"),
    }


def _historical_eps_anchor(
    official_drivers: pd.DataFrame,
    company: str,
    *,
    fallback_operating_profit_native_mn: float | None = None,
) -> dict[str, object]:
    """Derive FY2025 share count and a reported below-operating residual.

    ``total_revenue - operating_cost`` is deliberately named operating
    contribution rather than accounting operating profit. The official driver
    layer does not expose a uniformly parsed ``营业利润`` line across all
    issuers. The residual keeps the reported attributable-profit anchor without
    pretending that finance cost, tax, FX, associates or NCI have been
    separately forecast.
    """
    result: dict[str, object] = {
        "fy2025_total_revenue_native_mn": None,
        "fy2025_operating_cost_native_mn": None,
        "fy2025_revenue_less_operating_cost_native_mn": None,
        "fy2025_reported_operating_profit_native_mn": None,
        "fy2025_operating_profit_proxy_native_mn": None,
        "fy2025_profit_total_native_mn": None,
        "fy2025_attributable_net_income_native_mn": None,
        "fy2025_basic_eps_rmb_per_share": None,
        "fy2025_operating_contribution_native_mn": None,
        "fy2025_profit_total_below_operating_adjustment_native_mn": None,
        "fy2025_attributable_below_operating_adjustment_native_mn": None,
        "implied_basic_shares_mn": None,
        "eps_anchor_status": "missing_fy2025_official_basic_eps_or_profit",
        "profit_bridge_status": "missing_fy2025_reported_profit_bridge",
        "operating_contribution_method": "not_available",
    }
    if official_drivers.empty or not {"company", "statement_period", "metric", "value_native"}.issubset(official_drivers.columns):
        return result
    rows = official_drivers.loc[
        official_drivers["company"].eq(company)
        & official_drivers["statement_period"].eq("FY2025")
        & official_drivers["metric"].isin(
            [
                "total_revenue",
                "operating_cost",
                "profit_total",
                "attributable_net_income",
                "basic_eps",
                "operating_profit",
            ]
        )
    ]
    if rows.empty:
        return result
    indexed = rows.set_index("metric")

    def metric_value(metric: str) -> float | None:
        if metric not in indexed.index:
            return None
        return _num(indexed.loc[metric, "value_native"])

    revenue = metric_value("total_revenue")
    operating_cost = metric_value("operating_cost")
    profit_total = metric_value("profit_total")
    profit = metric_value("attributable_net_income")
    eps = metric_value("basic_eps")
    revenue_less_operating_cost = (
        revenue - operating_cost
        if revenue is not None and operating_cost is not None
        else None
    )
    reported_operating_profit = metric_value("operating_profit")
    operating_profit_proxy = (
        reported_operating_profit
        if reported_operating_profit is not None
        else _num(fallback_operating_profit_native_mn)
    )
    # Prefer the issuer's formal consolidated income-statement operating
    # profit when it is available.  Keep the old revenue-minus-cost bridge as
    # a named fallback for issuers whose PDF does not expose a safe row.
    operating_contribution = (
        operating_profit_proxy
        if operating_profit_proxy is not None
        else revenue_less_operating_cost
    )
    profit_adjustment = (
        profit_total - operating_contribution
        if profit_total is not None and operating_contribution is not None
        else None
    )
    attributable_adjustment = (
        profit - operating_contribution
        if profit is not None and operating_contribution is not None
        else None
    )
    shares = profit / eps if profit is not None and eps not in (None, 0) else None
    result.update(
        {
            "fy2025_total_revenue_native_mn": revenue,
            "fy2025_operating_cost_native_mn": operating_cost,
            "fy2025_revenue_less_operating_cost_native_mn": revenue_less_operating_cost,
            "fy2025_reported_operating_profit_native_mn": reported_operating_profit,
            "fy2025_operating_profit_proxy_native_mn": (
                operating_profit_proxy
                if reported_operating_profit is None
                else None
            ),
            "fy2025_profit_total_native_mn": profit_total,
            "fy2025_attributable_net_income_native_mn": profit,
            "fy2025_basic_eps_rmb_per_share": eps,
            "fy2025_operating_contribution_native_mn": operating_contribution,
            "fy2025_profit_total_below_operating_adjustment_native_mn": profit_adjustment,
            "fy2025_attributable_below_operating_adjustment_native_mn": attributable_adjustment,
            "implied_basic_shares_mn": shares,
            "eps_anchor_status": "fy2025_official_basic_eps_implied_share_count" if shares is not None and shares > 0 else "invalid_fy2025_eps_anchor",
            "profit_bridge_status": (
                "available_fy2025_reported_income_statement_residual"
                if reported_operating_profit is not None and attributable_adjustment is not None and profit_adjustment is not None
                else "available_fy2025_aggregate_operating_profit_proxy_residual"
                if fallback_operating_profit_native_mn is not None and attributable_adjustment is not None and profit_adjustment is not None
                else "available_fy2025_reported_below_operating_residual"
                if attributable_adjustment is not None and profit_adjustment is not None
                else "incomplete_fy2025_reported_profit_bridge"
            ),
            "operating_contribution_method": (
                "fy2025_reported_consolidated_income_statement_operating_profit"
                if reported_operating_profit is not None
                else "fy2025_v2_aggregate_operating_profit_proxy"
                if fallback_operating_profit_native_mn is not None
                else "fy2025_total_revenue_minus_operating_cost_fallback"
            ),
        }
    )
    return result


def _historical_waterfall_context(
    official_drivers: pd.DataFrame,
    company: str,
) -> dict[str, object]:
    """Carry disclosed FY2025 below-operating rows into the model output.

    This is an audit/context layer, not a forward forecast.  It makes clear
    which parts of net income are observed in the issuer report and which
    parts remain inside the v3 residual bridge.
    """
    waterfall_metrics = (
        "operating_profit",
        "finance_cost",
        "interest_expense",
        "investment_income",
        "other_income",
        "fair_value_change_income",
        "credit_impairment_loss",
        "asset_impairment_loss",
        "asset_disposal_income",
        "non_operating_income",
        "non_operating_expense",
        "income_tax_expense",
        "net_income_total",
        "minority_interest",
    )
    result: dict[str, object] = {
        f"fy2025_{metric}_native_mn": None for metric in waterfall_metrics
    }
    result.update(
        {
            "fy2025_waterfall_status": "missing_reported_fy2025_waterfall",
            "fy2025_waterfall_available_metric_count": 0,
            "fy2025_profit_total_reconciliation_error_native_mn": None,
            "fy2025_net_income_reconciliation_error_native_mn": None,
            "fy2025_attributable_reconciliation_error_native_mn": None,
            "fy2025_waterfall_reconciliation_status": "not_tested_missing_rows",
            "forward_waterfall_status": "not_modelled_forward",
        }
    )
    required = {"company", "statement_period", "metric", "value_native"}
    if official_drivers.empty or not required.issubset(official_drivers.columns):
        return result
    rows = official_drivers.loc[
        official_drivers["company"].eq(company)
        & official_drivers["statement_period"].eq("FY2025")
        & official_drivers["metric"].isin(waterfall_metrics)
    ]
    if rows.empty:
        return result
    available = 0
    for metric in waterfall_metrics:
        selected = rows.loc[rows["metric"].eq(metric), "value_native"]
        if selected.empty:
            continue
        value = _num(selected.iloc[0])
        if value is None:
            continue
        result[f"fy2025_{metric}_native_mn"] = value
        available += 1
    result["fy2025_waterfall_available_metric_count"] = available
    result["fy2025_waterfall_status"] = (
        "available_reported_fy2025_waterfall"
        if all(
            result.get(f"fy2025_{metric}_native_mn") is not None
            for metric in ("operating_profit", "finance_cost", "income_tax_expense", "net_income_total")
        )
        else "partial_reported_fy2025_waterfall"
    )
    # Reconcile the accounting identities that are actually represented in
    # the report layer.  The lower waterfall is deliberately tested
    # independently from the forward model so a parser or scope mismatch is
    # visible instead of being absorbed by the residual.
    def reported_value(metric: str) -> float | None:
        selected = official_drivers.loc[
            official_drivers["company"].eq(company)
            & official_drivers["statement_period"].eq("FY2025")
            & official_drivers["metric"].eq(metric),
            "value_native",
        ]
        return _num(selected.iloc[0]) if not selected.empty else None

    op = result.get("fy2025_operating_profit_native_mn")
    nonop_income = result.get("fy2025_non_operating_income_native_mn")
    nonop_expense = result.get("fy2025_non_operating_expense_native_mn")
    profit_total = reported_value("profit_total")
    tax = result.get("fy2025_income_tax_expense_native_mn")
    net_total = result.get("fy2025_net_income_total_native_mn")
    minority = result.get("fy2025_minority_interest_native_mn")
    attributable = reported_value("attributable_net_income")
    if all(value is not None for value in (op, nonop_income, nonop_expense, profit_total)):
        result["fy2025_profit_total_reconciliation_error_native_mn"] = (
            op + nonop_income - nonop_expense - profit_total
        )
    if all(value is not None for value in (profit_total, tax, net_total)):
        result["fy2025_net_income_reconciliation_error_native_mn"] = (
            profit_total - tax - net_total
        )
    if all(value is not None for value in (net_total, minority, attributable)):
        result["fy2025_attributable_reconciliation_error_native_mn"] = (
            net_total - minority - attributable
        )
    errors = [
        result.get("fy2025_profit_total_reconciliation_error_native_mn"),
        result.get("fy2025_net_income_reconciliation_error_native_mn"),
        result.get("fy2025_attributable_reconciliation_error_native_mn"),
    ]
    errors = [float(error) for error in errors if error is not None]
    if errors and max(abs(error) for error in errors) <= 5.0:
        result["fy2025_waterfall_reconciliation_status"] = "reconciles_core_profit_waterfall"
    elif errors:
        result["fy2025_waterfall_reconciliation_status"] = "reported_rows_do_not_fully_reconcile"
    else:
        result["fy2025_waterfall_reconciliation_status"] = "partial_reconciliation_missing_rows"
    return result


def _forward_waterfall_proxy(
    waterfall_context: dict[str, object],
    eps_anchor: dict[str, object],
    forward_assumptions: dict[str, object] | None = None,
    *,
    forecast_operating_contribution_native_mn: float | None,
    forecast_revenue_native_mn: float | None,
) -> dict[str, object]:
    """Build an explicitly labelled forward below-operating proxy.

    This is intentionally a parallel diagnostic rather than the primary v3
    net-income output.  It is only produced when the FY2025 formal waterfall
    has enough rows to reconcile.  Finance cost is scaled with forecast
    revenue because no forward debt schedule is available; other disclosed
    rows are carried at FY2025 absolute values; tax and NCI use conservative
    carry-forward assumptions.  The method is therefore a transparent stress
    bridge, not issuer guidance or a fully forecast accounting model.
    """
    default: dict[str, object] = {
        "forward_waterfall_status": "not_available_missing_reconciled_historical_waterfall",
        "forward_waterfall_method": "not_available",
        "forward_finance_cost_native_mn": None,
        "forward_other_income_native_mn": None,
        "forward_investment_income_native_mn": None,
        "forward_fair_value_change_income_native_mn": None,
        "forward_credit_impairment_loss_native_mn": None,
        "forward_asset_impairment_loss_native_mn": None,
        "forward_asset_disposal_income_native_mn": None,
        "forward_non_operating_income_native_mn": None,
        "forward_non_operating_expense_native_mn": None,
        "forward_income_tax_expense_native_mn": None,
        "forward_income_tax_method": "not_available",
        "forward_minority_interest_native_mn": None,
        "forward_minority_interest_share_pct": None,
        "forward_nci_share_based_native_mn": None,
        "forward_attributable_share_based_native_mn": None,
        "forward_nci_share_based_status": "not_available",
        "forward_profit_total_waterfall_proxy_native_mn": None,
        "forward_net_income_total_waterfall_proxy_native_mn": None,
        "forward_attributable_net_income_waterfall_proxy_native_mn": None,
        "forward_basic_eps_waterfall_proxy_rmb_per_share": None,
    }
    if waterfall_context.get("fy2025_waterfall_reconciliation_status") != "reconciles_core_profit_waterfall":
        return default
    required = (
        "finance_cost",
        "other_income",
        "investment_income",
        "fair_value_change_income",
        "credit_impairment_loss",
        "asset_impairment_loss",
        "asset_disposal_income",
        "non_operating_income",
        "non_operating_expense",
        "income_tax_expense",
        "minority_interest",
    )
    values: dict[str, float] = {}
    for metric in required:
        value = _num(waterfall_context.get(f"fy2025_{metric}_native_mn"))
        if value is None:
            return default
        values[metric] = value
    fy_revenue = _num(eps_anchor.get("fy2025_total_revenue_native_mn"))
    forecast_revenue = _num(forecast_revenue_native_mn)
    forecast_operating = _num(forecast_operating_contribution_native_mn)
    if fy_revenue in (None, 0) or forecast_revenue is None or forecast_operating is None:
        return default
    revenue_scale = forecast_revenue / fy_revenue
    forward_finance = values["finance_cost"] * revenue_scale
    # These rows are carried as absolute values because their future driver is
    # not identifiable from the free public source layer yet.
    carried = {
        metric: values[metric]
        for metric in required
        if metric != "finance_cost"
    }
    forward_profit_total = (
        forecast_operating
        + carried["other_income"]
        - forward_finance
        + carried["investment_income"]
        + carried["fair_value_change_income"]
        + carried["credit_impairment_loss"]
        + carried["asset_impairment_loss"]
        + carried["asset_disposal_income"]
        + carried["non_operating_income"]
        - carried["non_operating_expense"]
    )
    forward_net_total = forward_profit_total - carried["income_tax_expense"]
    forward_tax = carried["income_tax_expense"]
    forward_tax_method = "fy2025_absolute_carry"
    if forward_assumptions:
        effective_rate = _num(
            forward_assumptions.get("fy2025_effective_tax_rate_pct")
            if forward_assumptions.get("fy2025_effective_tax_rate_pct") is not None
            else forward_assumptions.get("forward_fy2025_effective_tax_rate_pct")
        )
        if effective_rate is not None:
            forward_tax = effective_rate / 100.0 * forward_profit_total
            forward_tax_method = "fy2025_effective_tax_rate_on_forecast_profit"
    forward_net_total = forward_profit_total - forward_tax
    forward_attributable = forward_net_total - carried["minority_interest"]
    # NCI share-based alternative.  When minority interest is a material share
    # of net income (e.g. Southern's 1,828m on 2,685m = 68%), carrying the
    # absolute FY2025 NCI into a much larger profit year understates the
    # profit sharing of consolidated subsidiaries.  This diagnostic computes
    # NCI as the FY2025 NCI/net-income ratio applied to the forward net
    # income; the ratio is only interpretable when net income is positive.
    fy_net_income = _num(waterfall_context.get("fy2025_net_income_total_native_mn"))
    nci_share = (
        carried["minority_interest"] / fy_net_income
        if fy_net_income not in (None, 0)
        else None
    )
    if (
        nci_share is not None
        and forward_net_total is not None
        and forward_net_total > 0
        and nci_share > 0
        and carried["minority_interest"] > 0
    ):
        forward_nci_share_based = nci_share * forward_net_total
        forward_attributable_share_based = forward_net_total - forward_nci_share_based
        nci_share_based_status = "available_share_based_nci"
    else:
        forward_nci_share_based = None
        forward_attributable_share_based = None
        nci_share_based_status = "not_interpretable_negative_or_zero_nci"
    shares = _num(eps_anchor.get("implied_basic_shares_mn"))
    result = {
        "forward_waterfall_status": "available_forward_waterfall_proxy",
        "forward_waterfall_method": (
            "finance_cost_scaled_with_forecast_revenue;"
            "other_income_investment_fair_value_impairment_asset_disposal_non_operating_tax_nci_carried_at_fy2025_absolute"
        ),
        "forward_finance_cost_native_mn": forward_finance,
        "forward_other_income_native_mn": carried["other_income"],
        "forward_investment_income_native_mn": carried["investment_income"],
        "forward_fair_value_change_income_native_mn": carried["fair_value_change_income"],
        "forward_credit_impairment_loss_native_mn": carried["credit_impairment_loss"],
        "forward_asset_impairment_loss_native_mn": carried["asset_impairment_loss"],
        "forward_asset_disposal_income_native_mn": carried["asset_disposal_income"],
        "forward_non_operating_income_native_mn": carried["non_operating_income"],
        "forward_non_operating_expense_native_mn": carried["non_operating_expense"],
        "forward_income_tax_expense_native_mn": forward_tax,
        "forward_income_tax_method": forward_tax_method,
        "forward_minority_interest_native_mn": carried["minority_interest"],
        "forward_minority_interest_share_pct": (
            nci_share * 100.0 if nci_share is not None else None
        ),
        "forward_nci_share_based_native_mn": forward_nci_share_based,
        "forward_attributable_share_based_native_mn": forward_attributable_share_based,
        "forward_nci_share_based_status": nci_share_based_status,
        "forward_profit_total_waterfall_proxy_native_mn": forward_profit_total,
        "forward_net_income_total_waterfall_proxy_native_mn": forward_net_total,
        "forward_attributable_net_income_waterfall_proxy_native_mn": forward_attributable,
        "forward_basic_eps_waterfall_proxy_rmb_per_share": (
            forward_attributable / shares if shares not in (None, 0) else None
        ),
    }
    return result


def _historical_revenue_split(
    official_drivers: pd.DataFrame,
    company: str,
    *,
    nonpassenger_residual_native_mn: float | None = None,
) -> dict[str, object]:
    """Build a disclosed cargo/other-revenue split without hiding annualization.

    Several issuers disclose cargo revenue in the annual report, while one
    covered group currently has a 1H cargo anchor but no parsed FY cargo line.
    In that case the 1H value is annualized and the status remains explicit.
    This split is only used when total, passenger and cargo revenue all have a
    usable anchor; otherwise v3 falls back to the legacy non-passenger
    residual rather than inventing a decomposition.
    """
    result: dict[str, object] = {
        "fy2025_cargo_revenue_native_mn": None,
        "fy2025_other_revenue_native_mn": None,
        "fy2025_passenger_revenue_split_native_mn": None,
        "revenue_split_status": "missing_fy2025_total_passenger_cargo_anchors",
        "revenue_split_method": "not_available",
    }
    required = {"company", "statement_period", "metric", "value_native"}
    if official_drivers.empty or not required.issubset(official_drivers.columns):
        return result

    rows = official_drivers.loc[official_drivers["company"].eq(company)].copy()

    def value(period: str, metric: str) -> float | None:
        selected = rows.loc[
            rows["statement_period"].eq(period) & rows["metric"].eq(metric)
        ]
        if selected.empty:
            return None
        return _num(selected.iloc[0].get("value_native"))

    fy_total = value("FY2025", "total_revenue")
    fy_passenger = value("FY2025", "passenger_revenue")
    fy_cargo = value("FY2025", "cargo_revenue")
    methods: list[str] = []
    fy_passenger_reported = fy_passenger is not None
    if fy_passenger is None and fy_total is not None and nonpassenger_residual_native_mn is not None:
        derived_passenger = fy_total - nonpassenger_residual_native_mn
        if derived_passenger >= 0:
            fy_passenger = derived_passenger
            methods.append("passenger_revenue_derived_from_fy2025_nonpassenger_residual")
    if fy_passenger is None:
        h1_passenger = value("1H2025", "passenger_revenue")
        if h1_passenger is not None:
            fy_passenger = 2.0 * h1_passenger
            methods.append("passenger_revenue_annualized_from_1H2025")
    elif fy_passenger_reported:
        methods.append("passenger_revenue_fy2025_reported")
    if fy_cargo is None:
        h1_cargo = value("1H2025", "cargo_revenue")
        if h1_cargo is not None:
            fy_cargo = 2.0 * h1_cargo
            methods.append("cargo_revenue_annualized_from_1H2025")
    else:
        methods.append("cargo_revenue_fy2025_reported")
    if fy_total is None or fy_passenger is None or fy_cargo is None:
        return result
    passenger_derived_from_residual = (
        "passenger_revenue_derived_from_fy2025_nonpassenger_residual" in methods
    )
    other = (
        nonpassenger_residual_native_mn - fy_cargo
        if passenger_derived_from_residual and nonpassenger_residual_native_mn is not None
        else fy_total - fy_passenger - fy_cargo
    )
    if other < -1e-6:
        result["revenue_split_status"] = "invalid_negative_other_revenue_residual"
        result["revenue_split_method"] = "+".join(methods)
        return result
    result.update(
        {
            "fy2025_cargo_revenue_native_mn": fy_cargo,
            "fy2025_other_revenue_native_mn": max(0.0, other),
            "fy2025_passenger_revenue_split_native_mn": fy_passenger,
            "revenue_split_status": "available_cargo_other_split",
            "revenue_split_method": "+".join(methods),
        }
    )
    return result


def _select_net_income_leg(
    *,
    residual_bridge_native: float | None,
    legacy_native: float | None,
    share_based_native: float | None,
    nci_share_status: object,
    regime_flip: bool,
    consensus_margin: float | None,
    forward_revenue_native: float | None,
    fx: float | None,
) -> tuple[
    float | None,
    float | None,
    float | None,
    float | None,
    str,
    bool,
]:
    """Select the forward attributable net-income leg.

    Priority:
      1. Share-based NCI forward -- for high-minority-interest carriers
         (e.g. Southern's 68% NCI share) the raw residual bridge, which
         carries the FY2025 *absolute* below-operating adjustment into a much
         larger forward profit year, overstates attributable net income,
         because NCI and tax scale with the larger profit.  When the
         share-based forward is interpretable and diverges materially from
         the raw bridge it becomes the primary leg; the raw bridge stays
         available as a diagnostic column.
      2. Consensus-margin guard on a regime flip -- loss-year carriers whose
         FY2025 below-operating residual embeds loss-year artifacts that do
         not scale into a profitable year.
      3. Raw auditable residual bridge (falling back to the legacy ratio).

    Returns ``(proxy_native, proxy_usd, guarded_native, guarded_usd, leg,
    share_based_override)`` where the guarded pair is the applied forward
    attributable net income and ``proxy`` reflects the same applied leg.
    """
    raw_native = (
        residual_bridge_native
        if residual_bridge_native is not None
        else legacy_native
    )
    raw_usd = raw_native / fx if raw_native is not None and fx else None

    share_based_override = (
        nci_share_status == "available_share_based_nci"
        and share_based_native is not None
        and residual_bridge_native is not None
        and residual_bridge_native != 0
        and (
            abs(residual_bridge_native - share_based_native)
            / abs(residual_bridge_native)
            > 0.40
        )
    )

    if share_based_override:
        guarded_native = share_based_native
        guarded_usd = share_based_native / fx if fx else None
        leg = "share_based_nci_forward"
    elif (
        regime_flip
        and consensus_margin is not None
        and forward_revenue_native is not None
    ):
        guarded_native = consensus_margin / 100.0 * forward_revenue_native
        guarded_usd = guarded_native / fx if fx else None
        leg = "consensus_margin_guard_regime_flip"
    else:
        guarded_native = raw_native
        guarded_usd = raw_usd
        leg = (
            "residual_bridge"
            if residual_bridge_native is not None
            else "legacy_conversion"
        )
    # The proxy pair tracks the applied leg so downstream consumers (e.g. the
    # H1-2026 validation playbook) read the operative forward attributable net
    # income rather than the raw residual diagnostic.
    proxy_native = guarded_native
    proxy_usd = guarded_usd
    return (
        proxy_native,
        proxy_usd,
        guarded_native,
        guarded_usd,
        leg,
        share_based_override,
    )


def build_airline_earnings_model_v3(
    *,
    v2_bridge: pd.DataFrame | None = None,
    cargo: pd.DataFrame | None = None,
    postal: pd.DataFrame | None = None,
    travel_demand_events: pd.DataFrame | None = None,
    airport_traffic: pd.DataFrame | None = None,
    cargo_airport_bridge: pd.DataFrame | None = None,
    cargo_yield_bridge: pd.DataFrame | None = None,
    forward_assumptions: pd.DataFrame | None = None,
    caac: pd.DataFrame | None = None,
    route_events: pd.DataFrame | None = None,
    hsr_coverage: pd.DataFrame | None = None,
    fuel_matrix: pd.DataFrame | None = None,
    fuel_recovery: pd.DataFrame | None = None,
    official_drivers: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build v3 rows with separate cargo/other revenue and residual net income."""
    if v2_bridge is None:
        v2_bridge = _read(V2_COMPANY_FORECAST_PATH)
        if v2_bridge.empty:
            v2_bridge = build_airline_company_financial_forecast_bridge()
    cargo = cargo if cargo is not None else _read(CARGO_PATH)
    postal = postal if postal is not None else _read(POSTAL_PATH)
    travel_demand_events = (
        travel_demand_events
        if travel_demand_events is not None
        else _read(TRAVEL_DEMAND_PATH)
    )
    airport_traffic = (
        airport_traffic
        if airport_traffic is not None
        else _read(AIRPORT_TRAFFIC_PATH)
    )
    cargo_airport_bridge = (
        cargo_airport_bridge
        if cargo_airport_bridge is not None
        else _read(CARGO_AIRPORT_BRIDGE_PATH)
    )
    cargo_yield_bridge = (
        cargo_yield_bridge
        if cargo_yield_bridge is not None
        else _read(CARGO_YIELD_BRIDGE_PATH)
    )
    forward_assumptions = (
        forward_assumptions
        if forward_assumptions is not None
        else _read(FORWARD_ASSUMPTIONS_PATH)
    )
    caac = caac if caac is not None else _read(CAAC_PATH)
    route_events = route_events if route_events is not None else _read(CAAC_ROUTE_LICENCE_PATH)
    hsr_coverage = hsr_coverage if hsr_coverage is not None else _read(HSR_COVERAGE_PATH)
    fuel_matrix = fuel_matrix if fuel_matrix is not None else _read(FUEL_MATRIX_PATH)
    fuel_recovery = fuel_recovery if fuel_recovery is not None else _read(FUEL_RECOVERY_PATH)
    official_drivers = official_drivers if official_drivers is not None else _read(OFFICIAL_DRIVERS_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    if v2_bridge.empty:
        raise ValueError("Cannot build airline v3 without the company forecast bridge")

    rows: list[dict[str, object]] = []
    for _, base in v2_bridge.iterrows():
        company = str(base.get("company", ""))
        scenario = str(base.get("scenario", ""))
        as_of_date = str(base.get("as_of_date", ""))[:10]
        signal = _latest_trade_signal(cargo, as_of_date=as_of_date)
        postal_signal = _latest_postal_sector_signal(postal, as_of_date=as_of_date)
        travel_signal = _latest_travel_demand_signal(
            travel_demand_events,
            as_of_date=as_of_date,
        )
        airport_signal = _latest_airport_traffic_signal(
            airport_traffic,
            as_of_date=as_of_date,
        )
        caac_signal = _latest_caac_sector_signal(caac, as_of_date=as_of_date)
        cargo_blend = _blended_cargo_demand_signal(signal, caac_signal, postal_signal)
        hsr_signal = _company_hsr_context(hsr_coverage, company)
        route_signal = _company_caac_route_licence_context(
            route_events,
            company,
            as_of_date=as_of_date,
        )
        fuel_signal = _company_fuel_context(fuel_matrix, company)
        recovery_signal = _latest_fuel_surcharge_recovery_context(fuel_recovery)
        cargo_bridge_signal = _company_cargo_airport_bridge_context(
            cargo_airport_bridge,
            company,
        )
        cargo_yield_signal = _company_cargo_yield_bridge_context(
            cargo_yield_bridge,
            company,
        )
        forward_assumption_signal = _company_forward_assumptions_context(
            forward_assumptions,
            company,
        )
        historical_fx = _num(base.get("actual_fx_native_per_usd")) or 7.0
        v2_operating_profit_proxy_native = (
            _num(base.get("actual_operating_profit_usd_mn")) * historical_fx
            if _num(base.get("actual_operating_profit_usd_mn")) is not None
            else None
        )
        eps_anchor = _historical_eps_anchor(
            official_drivers,
            company,
            fallback_operating_profit_native_mn=v2_operating_profit_proxy_native,
        )
        waterfall_context = _historical_waterfall_context(official_drivers, company)
        signal_yoy = _num(signal.get("cargo_proxy_yoy_pct"))
        shock = SCENARIO_CARGO_SHOCK.get(scenario)
        blended_yoy = _num(cargo_blend.get("cargo_proxy_blended_yoy_pct"))
        cargo_demand_yoy = blended_yoy if blended_yoy is not None else signal_yoy
        cargo_growth = (
            cargo_demand_yoy + shock
            if cargo_demand_yoy is not None and shock is not None
            else None
        )
        fy_nonpassenger = _num(base.get("fy2025_nonpassenger_revenue_native_mn"))
        passenger_revenue = _num(base.get("forecast_passenger_revenue_native_mn"))
        revenue_split = _historical_revenue_split(
            official_drivers,
            company,
            nonpassenger_residual_native_mn=fy_nonpassenger,
        )
        historical_passenger_split = _num(revenue_split.get("fy2025_passenger_revenue_split_native_mn"))
        historical_cargo = _num(revenue_split.get("fy2025_cargo_revenue_native_mn"))
        historical_other = _num(revenue_split.get("fy2025_other_revenue_native_mn"))
        passenger_growth = (
            100.0 * passenger_revenue / historical_passenger_split - 100.0
            if passenger_revenue is not None and historical_passenger_split not in (None, 0)
            else None
        )
        other_growth = passenger_growth if passenger_growth is not None else _num(
            base.get("nonpassenger_revenue_growth_assumption_pct")
        )
        split_available = (
            revenue_split.get("revenue_split_status") == "available_cargo_other_split"
            and historical_cargo is not None
            and historical_other is not None
            and cargo_growth is not None
            and other_growth is not None
        )
        v3_cargo_revenue = (
            historical_cargo * (1.0 + cargo_growth / 100.0)
            if split_available
            else None
        )
        v3_other_revenue = (
            historical_other * (1.0 + other_growth / 100.0)
            if split_available
            else None
        )
        if split_available:
            v3_nonpassenger_revenue = v3_cargo_revenue + v3_other_revenue
            v3_nonpassenger_growth = (
                100.0 * v3_nonpassenger_revenue / fy_nonpassenger - 100.0
                if fy_nonpassenger not in (None, 0)
                else None
            )
            nonpassenger_split_status = "available_cargo_proxy_plus_other_passenger_growth"
        else:
            v3_nonpassenger_growth = cargo_growth
            v3_nonpassenger_revenue = (
                fy_nonpassenger * (1.0 + v3_nonpassenger_growth / 100.0)
                if fy_nonpassenger is not None and v3_nonpassenger_growth is not None
                else None
            )
            nonpassenger_split_status = "legacy_nonpassenger_residual_fallback"
        v3_revenue_native = (
            passenger_revenue + v3_nonpassenger_revenue
            if passenger_revenue is not None and v3_nonpassenger_revenue is not None
            else None
        )
        v2_cost_native = _num(base.get("forecast_operating_cost_native_mn"))
        v3_operating_profit_native = (
            v3_revenue_native - v2_cost_native
            if v3_revenue_native is not None and v2_cost_native is not None
            else None
        )
        forward_waterfall = _forward_waterfall_proxy(
            waterfall_context,
            eps_anchor,
            forward_assumption_signal,
            forecast_operating_contribution_native_mn=v3_operating_profit_native,
            forecast_revenue_native_mn=v3_revenue_native,
        )
        fx = _num(base.get("actual_fx_native_per_usd"))
        for native_key in (
            "forward_profit_total_waterfall_proxy_native_mn",
            "forward_net_income_total_waterfall_proxy_native_mn",
            "forward_attributable_net_income_waterfall_proxy_native_mn",
            "forward_nci_share_based_native_mn",
            "forward_attributable_share_based_native_mn",
        ):
            value = _num(forward_waterfall.get(native_key))
            usd_key = native_key.replace("_native_mn", "_usd_mn")
            forward_waterfall[usd_key] = value / fx if value is not None and fx else None
        v3_revenue_usd = v3_revenue_native / fx if v3_revenue_native is not None and fx else None
        v3_operating_profit_usd = (
            v3_operating_profit_native / fx
            if v3_operating_profit_native is not None and fx
            else None
        )
        conversion = _num(base.get("net_to_operating_profit_conversion"))
        legacy_net_profit_proxy_usd = (
            v3_operating_profit_usd * conversion
            if v3_operating_profit_usd is not None and conversion is not None
            else None
        )
        legacy_net_profit_proxy_native = (
            legacy_net_profit_proxy_usd * fx
            if legacy_net_profit_proxy_usd is not None and fx
            else None
        )
        attributable_adjustment = _num(
            eps_anchor.get("fy2025_attributable_below_operating_adjustment_native_mn")
        )
        profit_total_adjustment = _num(
            eps_anchor.get("fy2025_profit_total_below_operating_adjustment_native_mn")
        )
        v3_attributable_net_income_bridge_native = (
            v3_operating_profit_native + attributable_adjustment
            if v3_operating_profit_native is not None and attributable_adjustment is not None
            else None
        )
        v3_profit_total_bridge_native = (
            v3_operating_profit_native + profit_total_adjustment
            if v3_operating_profit_native is not None and profit_total_adjustment is not None
            else None
        )
        # Prefer the auditable reported residual bridge. Retain the old ratio
        # only when a legacy/test input does not provide the five official
        # FY2025 anchors.
        v3_net_profit_proxy_native = (
            v3_attributable_net_income_bridge_native
            if v3_attributable_net_income_bridge_native is not None
            else legacy_net_profit_proxy_native
        )
        v3_net_profit_proxy_usd = (
            v3_net_profit_proxy_native / fx
            if v3_net_profit_proxy_native is not None and fx
            else None
        )
        # Regime-flip guard for loss-year carriers.  When FY2025 operating
        # profit is negative (or the v2 aggregate proxy is negative) but the
        # forward operating profit is positive, the FY2025 absolute
        # below-operating residual embeds loss-year artifacts (deferred-tax
        # reversals, one-off impairments and minority structures) that do not
        # scale into a profitable year.  In that regime the net-income leg
        # switches to the dated consensus margin applied to forecast revenue;
        # the raw residual bridge is retained as a diagnostic column.
        fy2025_op = _num(eps_anchor.get("fy2025_reported_operating_profit_native_mn"))
        if fy2025_op is None:
            fy2025_op = _num(eps_anchor.get("fy2025_operating_profit_proxy_native_mn"))
        consensus_revenue = _num(base.get("consensus_fy2026_revenue_usd_mn"))
        consensus_profit = _num(base.get("consensus_fy2026_profit_usd_mn"))
        consensus_margin = (
            100.0 * consensus_profit / consensus_revenue
            if consensus_profit is not None and consensus_revenue not in (None, 0)
            else None
        )
        regime_flip = (
            fy2025_op is not None
            and fy2025_op < 0
            and v3_operating_profit_native is not None
            and v3_operating_profit_native > 0
        )
        (
            v3_net_profit_proxy_native,
            v3_net_profit_proxy_usd,
            v3_net_profit_consensus_guarded_native,
            v3_net_profit_consensus_guarded_usd,
            net_income_leg,
            share_based_override,
        ) = _select_net_income_leg(
            residual_bridge_native=v3_attributable_net_income_bridge_native,
            legacy_native=legacy_net_profit_proxy_native,
            share_based_native=_num(
                forward_waterfall.get("forward_attributable_share_based_native_mn")
            ),
            nci_share_status=forward_waterfall.get("forward_nci_share_based_status"),
            regime_flip=bool(regime_flip),
            consensus_margin=consensus_margin,
            forward_revenue_native=v3_revenue_native,
            fx=fx,
        )
        v3_attributable_net_income_bridge_usd = (
            v3_attributable_net_income_bridge_native / fx
            if v3_attributable_net_income_bridge_native is not None and fx
            else None
        )
        v3_profit_total_bridge_usd = (
            v3_profit_total_bridge_native / fx
            if v3_profit_total_bridge_native is not None and fx
            else None
        )
        v2_fuel_overlay_pre_tax_usd = _num(base.get("fuel_overlay_pre_tax_usd_mn"))
        v2_fuel_overlay_pre_tax_native = (
            v2_fuel_overlay_pre_tax_usd * fx
            if v2_fuel_overlay_pre_tax_usd is not None and fx
            else None
        )
        v3_operating_profit_after_fuel_native = (
            v3_operating_profit_native + v2_fuel_overlay_pre_tax_native
            if v3_operating_profit_native is not None and v2_fuel_overlay_pre_tax_native is not None
            else v3_operating_profit_native
        )
        v3_operating_profit_after_fuel_usd = (
            v3_operating_profit_after_fuel_native / fx
            if v3_operating_profit_after_fuel_native is not None and fx
            else None
        )
        implied_shares = _num(eps_anchor.get("implied_basic_shares_mn"))
        v3_basic_eps_proxy = (
            v3_net_profit_proxy_native / implied_shares
            if v3_net_profit_proxy_native is not None and implied_shares and implied_shares > 0
            else None
        )
        rows.append(
            {
                "dataset_id": "airline_earnings_model_v3",
                "model_version": "v3_external_cargo_split_residual_net_income_bridge",
                "company": company,
                "parent_group": base.get("parent_group"),
                "ticker": base.get("ticker"),
                "scenario": scenario,
                "forecast_horizon": base.get("forecast_horizon", "FY2026_pre_interim"),
                "as_of_date": as_of_date,
                "v2_forecast_nonpassenger_growth_pct": _num(base.get("nonpassenger_revenue_growth_assumption_pct")),
                "v2_forecast_nonpassenger_revenue_native_mn": _num(base.get("forecast_nonpassenger_revenue_native_mn")),
                "fy2025_cargo_revenue_native_mn": historical_cargo,
                "fy2025_other_revenue_native_mn": historical_other,
                "fy2025_passenger_revenue_split_native_mn": historical_passenger_split,
                "revenue_split_status": revenue_split.get("revenue_split_status"),
                "revenue_split_method": revenue_split.get("revenue_split_method"),
                "cargo_proxy_yoy_pct": signal_yoy,
                "cargo_proxy_export_yoy_pct": signal.get("cargo_proxy_export_yoy_pct"),
                "cargo_proxy_import_yoy_pct": signal.get("cargo_proxy_import_yoy_pct"),
                "cargo_proxy_total_trade_yoy_pct": signal.get("cargo_proxy_total_trade_yoy_pct"),
                "cargo_proxy_scenario_shock_pct": shock,
                **cargo_blend,
                "v3_cargo_revenue_growth_pct": cargo_growth if split_available else None,
                "v3_cargo_revenue_native_mn": v3_cargo_revenue,
                "v3_other_revenue_growth_pct": other_growth if split_available else None,
                "v3_other_revenue_native_mn": v3_other_revenue,
                "v3_nonpassenger_revenue_split_status": nonpassenger_split_status,
                "v3_nonpassenger_revenue_growth_pct": v3_nonpassenger_growth,
                "v3_nonpassenger_revenue_native_mn": v3_nonpassenger_revenue,
                "v3_passenger_revenue_native_mn": passenger_revenue,
                "v3_revenue_native_mn": v3_revenue_native,
                "v3_operating_cost_native_mn": v2_cost_native,
                "v3_operating_profit_native_mn": v3_operating_profit_native,
                "v3_revenue_usd_mn": v3_revenue_usd,
                "v3_operating_profit_usd_mn": v3_operating_profit_usd,
                "v2_fuel_shock_pct": _num(base.get("fuel_shock_pct")),
                "v2_fuel_overlay_pre_tax_usd_mn": v2_fuel_overlay_pre_tax_usd,
                "v3_fuel_overlay_pre_tax_native_mn": v2_fuel_overlay_pre_tax_native,
                "v3_operating_profit_after_fuel_native_mn": v3_operating_profit_after_fuel_native,
                "v3_operating_profit_after_fuel_usd_mn": v3_operating_profit_after_fuel_usd,
                "v3_profit_total_bridge_native_mn": v3_profit_total_bridge_native,
                "v3_profit_total_bridge_usd_mn": v3_profit_total_bridge_usd,
                "v3_attributable_net_income_bridge_native_mn": v3_attributable_net_income_bridge_native,
                "v3_attributable_net_income_bridge_usd_mn": v3_attributable_net_income_bridge_usd,
                "v3_net_profit_proxy_native_mn": v3_net_profit_proxy_native,
                "v3_net_profit_proxy_usd_mn": v3_net_profit_proxy_usd,
                "v3_net_profit_consensus_guarded_native_mn": v3_net_profit_consensus_guarded_native,
                "v3_net_profit_consensus_guarded_usd_mn": v3_net_profit_consensus_guarded_usd,
                "net_income_leg": net_income_leg,
                "regime_flip_flag": bool(regime_flip),
                "consensus_implied_margin_pct": consensus_margin,
                "v3_basic_eps_proxy_rmb_per_share": v3_basic_eps_proxy,
                "v3_basic_eps_bridge_rmb_per_share": v3_basic_eps_proxy,
                "v3_legacy_net_profit_proxy_native_mn": legacy_net_profit_proxy_native,
                "v3_legacy_net_profit_proxy_usd_mn": legacy_net_profit_proxy_usd,
                "fy2025_total_revenue_native_mn": eps_anchor.get("fy2025_total_revenue_native_mn"),
                "fy2025_operating_cost_native_mn": eps_anchor.get("fy2025_operating_cost_native_mn"),
                "fy2025_revenue_less_operating_cost_native_mn": eps_anchor.get("fy2025_revenue_less_operating_cost_native_mn"),
                "fy2025_reported_operating_profit_native_mn": eps_anchor.get("fy2025_reported_operating_profit_native_mn"),
                "fy2025_operating_profit_proxy_native_mn": eps_anchor.get("fy2025_operating_profit_proxy_native_mn"),
                "fy2025_profit_total_native_mn": eps_anchor.get("fy2025_profit_total_native_mn"),
                "fy2025_attributable_net_income_native_mn": eps_anchor.get("fy2025_attributable_net_income_native_mn"),
                "fy2025_basic_eps_rmb_per_share": eps_anchor.get("fy2025_basic_eps_rmb_per_share"),
                "fy2025_operating_contribution_native_mn": eps_anchor.get("fy2025_operating_contribution_native_mn"),
                "fy2025_profit_total_below_operating_adjustment_native_mn": profit_total_adjustment,
                "fy2025_attributable_below_operating_adjustment_native_mn": attributable_adjustment,
                "implied_basic_shares_mn": implied_shares,
                "operating_contribution_method": eps_anchor.get("operating_contribution_method"),
                "v3_revenue_gap_to_consensus_pct": (
                    100.0 * v3_revenue_usd / consensus_revenue - 100.0
                    if v3_revenue_usd is not None and consensus_revenue
                    else None
                ),
                "v3_net_profit_gap_to_consensus_pct": (
                    100.0 * v3_net_profit_proxy_usd / consensus_profit - 100.0
                    if v3_net_profit_proxy_usd is not None and consensus_profit
                    else None
                ),
                "consensus_fy2026_revenue_usd_mn": consensus_revenue,
                "consensus_fy2026_profit_usd_mn": consensus_profit,
                "v3_eps_status": (
                    "proxy_using_fy2025_reported_below_operating_residual_and_basic_eps_share_count"
                    if v3_basic_eps_proxy is not None and attributable_adjustment is not None
                    else "legacy_proxy_using_fy2025_official_basic_eps_implied_share_count"
                    if v3_basic_eps_proxy is not None
                    else "not_modelled_missing_point_in_time_share_count_bridge"
                ),
                "eps_anchor_status": eps_anchor.get("eps_anchor_status"),
                "profit_bridge_status": eps_anchor.get("profit_bridge_status"),
                "cargo_proxy_status": signal.get("cargo_proxy_status"),
                "cargo_proxy_method": signal.get("cargo_proxy_method"),
                "cargo_proxy_observation_month_start": signal.get("cargo_proxy_observation_month_start"),
                "cargo_proxy_observation_month_end": signal.get("cargo_proxy_observation_month_end"),
                "cargo_proxy_source_snapshot_date": signal.get("cargo_proxy_source_snapshot_date"),
                "cargo_proxy_observations": signal.get("cargo_proxy_observations"),
                **postal_signal,
                **travel_signal,
                **airport_signal,
                **caac_signal,
                **route_signal,
                **hsr_signal,
                **fuel_signal,
                **recovery_signal,
                **cargo_bridge_signal,
                **cargo_yield_signal,
                **forward_assumption_signal,
                **waterfall_context,
                **forward_waterfall,
                "model_status": "available_with_external_cargo_proxy" if v3_revenue_native is not None else "incomplete_missing_nonpassenger_base",
                "net_income_status": (
                    "share_based_nci_forward_prorates_fy2025_minority_interest_share"
                    if share_based_override
                    else "proxy_operating_profit_plus_fy2025_reported_below_operating_residual"
                    if v3_attributable_net_income_bridge_usd is not None
                    else "legacy_proxy_operating_profit_times_historical_conversion"
                    if legacy_net_profit_proxy_usd is not None
                    else "not_modelled"
                ),
                "point_in_time_status": "mixed_issuer_and_latest_trade_snapshot_not_full_pit",
                "source_quality": "derived_v3_existing_issuer_bridge_plus_mofcom_caac_spb_open_data",
                "source_note": "Passenger revenue and aggregate cost inherit the existing unit-economics bridge. Where FY2025 total/passenger/cargo anchors reconcile, v3 grows reported cargo revenue with the external MOFCOM trade proxy plus scenario shock and grows the other-revenue residual with forecast passenger-revenue growth; otherwise it falls back to the legacy non-passenger residual. CAAC, SPB, MOT/MCT holiday and airport-hub data are sector context only and do not override company ASK/RPK or cargo revenue; SPB, MOT/MCT and airport throughput are broad logistics/travel/hub proxies. HSR is route context only. Fuel overlay is retained as a pre-tax sensitivity; hedge and surcharge fields are disclosure/policy context, not realized pass-through. Net income/EPS use forecast operating contribution plus the FY2025 official attributable-profit minus operating-contribution residual when the five-anchor report bridge is complete; this residual combines finance cost, FX, tax, associates and NCI and is not a granular forward waterfall. For high-minority-interest carriers (e.g. China Southern, 68% NCI share) where the forward share-based NCI proration diverges materially from the raw absolute residual bridge, net income/EPS switch to the share-based NCI forward leg (net_income_leg='share_based_nci_forward') and the raw residual bridge is retained as a diagnostic column.",
                "retrieved_at": retrieved,
            }
        )
    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


KPI_COVERAGE_ROWS = [
    ("ASK", "operating_capacity", "modelled", "issuer monthly operating releases; FY/H1 bridge", "Forecast ASK is directly carried from company traffic assumptions; route-level future capacity remains incomplete."),
    ("RPK", "passenger_demand", "modelled", "issuer monthly operating releases; FY/H1 bridge", "Forecast RPK is modelled from issuer anchor/scenario assumptions."),
    ("Passenger load factor", "passenger_demand", "modelled", "RPK / ASK", "Derived weighted load factor; route/cabin mix is not separately modelled."),
    ("Passenger revenue", "revenue", "modelled", "passenger RASK proxy x ASK", "Issuer passenger revenue anchors are available for covered FY/H1 periods; forward passenger revenue remains a RASK proxy."),
    ("Passenger yield / RASK", "pricing", "partial", "issuer disclosed yield where available; otherwise total revenue / ASK proxy", "Not a clean route/cabin realized yield series across all names."),
    ("Operating profit", "earnings", "modelled", "forecast revenue less aggregate operating-cost bridge", "Where FY2025 reported operating profit is available it is used as the historical residual anchor; forward cost mix is still aggregated."),
    ("Cargo demand", "revenue_driver", "proxy", "MOFCOM monthly exports/imports; issuer cargo tonnes where available", "External trade proxy is broad and not airline-specific."),
    ("Postal / express demand", "revenue_driver", "proxy", "State Post Bureau cumulative revenue/parcel volume and segment split", "Broad e-commerce/logistics context only; it is not airline cargo demand and does not directly change the revenue forecast."),
    ("Holiday travel demand", "sector_demand", "proxy", "MOT Spring Festival transport and MCT holiday tourism/spend events", "Low-frequency event control; duration-normalized but not converted into monthly company RPK."),
    ("Airport hub traffic", "sector_demand", "proxy", "issuer monthly airport production bulletins (Shanghai, Shenzhen, Guangzhou)", "Airport throughput includes many carriers and is hub context only; it is not company RPK or revenue."),
    ("Cargo revenue", "revenue", "partial", "Reported FY2025 cargo revenue grown by external trade proxy where anchors reconcile", "Cargo demand is not airline-specific and cargo yield remains incomplete; fallback residual is retained where the annual split is unavailable."),
    ("Cargo tonnage / cargo yield", "revenue_driver", "partial", "issuer cargo/RTK/yield disclosures where available", "No uniform airline-by-airline forward tonnage and yield model."),
    ("Airport-cargo bridge calibration", "revenue_driver", "proxy", "airport cargo throughput versus company cargo tonnage/revenue", "Hub mapping is directional; airport throughput includes many carriers and is calibration context only."),
    ("Cargo-yield forward revenue bridge", "revenue", "partial", "reported cargo revenue per tonne applied to H1-2026 issuer tonnage", "Yield is not uniform by route/commodity; tonnage is preliminary monthly data and the Spring/Juneyao anchor is FY-annualized."),
    ("Ancillary / other revenue", "revenue", "partial", "FY2025 total/passenger/cargo residual grown with forecast passenger-revenue growth", "No separate ancillary attach-rate/ARPU model; this is a transparent residual proxy rather than a disclosed forward segment forecast."),
    ("Jet fuel price", "cost_driver", "modelled", "EIA daily/weekly benchmark", "Benchmark is not company realized purchase price."),
    ("Fuel volume", "cost_driver", "partial", "fuel cost per ASK / aggregate CASK", "Volume is not independently forecast from block hours and aircraft type."),
    ("Fuel hedge", "cost_driver", "partial", "issuer hedging disclosure coverage", "Disclosure/status exists, but hedge book cash-flow accounting is not fully integrated."),
    ("Fuel pass-through", "cost_driver", "partial", "official surcharge schedules plus dated surcharge-to-fuel recovery proxy", "Regulated per-passenger surcharges are not realized fuel-cost recovery; the recovery ratio is context only."),
    ("Non-fuel CASK", "cost_driver", "modelled", "aggregate operating-cost / ASK bridge", "Maintenance, labor, airport and distribution costs are not fully decomposed."),
    ("Fleet count", "supply_driver", "partial", "issuer/Cathay fleet disclosures", "Historical fleet is available; forward delivery/retirement schedule is incomplete for every name."),
    ("Aircraft utilization", "supply_driver", "partial", "issuer disclosed daily utilization where available", "Not independently forecast by fleet type/route."),
    ("HSR substitution", "demand_risk", "proxy_monitor", "12306/Ctrip route observations", "Route-specific demand elasticity and revenue impact are not integrated."),
    ("Net income", "earnings", "proxy", "forecast operating contribution + FY2025 reported below-operating residual", "Residual combines finance cost, FX, tax, associates and NCI; it is more transparent than a net-to-operating ratio but is not a granular forecast."),
    ("EPS", "earnings", "proxy", "residual net-income proxy / FY2025 official basic-EPS implied share count", "This is not diluted EPS and does not model future issuance/buybacks; the below-operating residual is carried forward."),
    ("Finance cost / FX / tax / associates", "earnings", "partial", "reported FY2025 waterfall anchors plus residual forward bridge", "The historical waterfall is now carried into v3; forward finance cost, FX, tax and associate income are still not separately forecast."),
    ("Forward waterfall proxy", "earnings", "partial", "reconciled FY2025 waterfall; finance cost scaled with forecast revenue; other rows carried", "Currently available only where the historical formal waterfall reconciles; it is a scenario diagnostic, not the primary EPS forecast."),
    ("Forward tax and FX assumptions", "earnings", "partial", "FY2025 effective tax rate (curated anchors where needed) and latest ECB USD/CNY carry", "Tax rate is historical and FX is a carry assumption, not a forward regime view; loss/reversal cases keep absolute tax."),
    ("Forward diluted share count / dilution", "earnings", "not_modelled", "FY2025 basic-EPS implied share count only", "No forward issuance, buyback, option or minority-ownership forecast."),
    ("Consensus revenue/profit", "expectations", "snapshot", "free public consensus discovery layers", "Useful comparator but not complete broker-vintage consensus for every issuer."),
    ("Valuation P/S/P/E/P/B", "valuation", "modelled", "free market/financial history and valuation bands", "Historical multiples still inherit denominator and point-in-time coverage caveats."),
]


def build_airline_earnings_model_v3_kpi_coverage(
    *,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Persist the explicit modelled/partial/proxy/unmodelled KPI contract."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    result = pd.DataFrame(
        [
            {
                "dataset_id": "airline_earnings_model_v3_kpi_coverage",
                "kpi": kpi,
                "kpi_category": category,
                "coverage_status": status,
                "current_source_or_method": method,
                "research_caveat": caveat,
                "is_safe_as_final_thesis_input": status == "modelled",
                "retrieved_at": retrieved,
            }
            for kpi, category, status, method, caveat in KPI_COVERAGE_ROWS
        ]
    )
    result.to_csv(COVERAGE_OUTPUT_PATH, index=False)
    return result


def fetch_airline_earnings_model_v3() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build v3 and its KPI coverage artifact."""
    retrieved = datetime.now(timezone.utc).isoformat()
    model = build_airline_earnings_model_v3(retrieved_at=retrieved)
    coverage = build_airline_earnings_model_v3_kpi_coverage(retrieved_at=retrieved)
    return model, coverage


__all__ = [
    "COVERAGE_OUTPUT_PATH",
    "OUTPUT_PATH",
    "build_airline_earnings_model_v3",
    "build_airline_earnings_model_v3_kpi_coverage",
    "fetch_airline_earnings_model_v3",
]
