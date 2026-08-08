"""Fuel-price shock scenarios for airline long/short research."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


BRIDGE_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
OFFICIAL_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
ENERGY_PATH = NORMALIZED_DIR / "airline_energy_prices.parquet"
FX_PATH = NORMALIZED_DIR / "airline_fx_rates.parquet"
SURCHARGE_PATH = NORMALIZED_DIR / "airline_fuel_surcharges.parquet"
SCENARIOS = (-20.0, -10.0, -5.0, 5.0, 10.0, 20.0)

SCENARIO_COLUMNS = [
    "dataset_id", "company", "primary_market_ticker", "baseline_period",
    "native_currency", "fuel_cost_native_mn", "fuel_cost_share_pct",
    "scenario_fuel_price_change_pct", "post_shock_fuel_cost_native_mn",
    "pre_tax_profit_impact_native_mn", "scenario_method",
    "issuer_sensitivity_available", "issuer_sensitivity_source_page",
    "jet_fuel_observation_date", "jet_fuel_spot_usd_per_gallon",
    "fx_pair", "fx_observation_date", "fx_value_quote_per_usd",
    "jet_fuel_spot_native_per_gallon", "fuel_cost_usd_mn",
    "post_shock_fuel_cost_usd_mn", "pre_tax_profit_impact_usd_mn",
    "surcharge_effective_from", "surcharge_reference", "surcharge_source_url",
    "source_quality", "source_note", "retrieved_at",
]


def _num(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _energy_snapshot() -> dict[str, Any]:
    if not ENERGY_PATH.exists():
        return {}
    frame = pd.read_parquet(ENERGY_PATH)
    frame = frame.loc[
        frame["frequency"].eq("weekly")
        & frame["series_id"].eq("EER_EPJK_PF4_RGC_DPG")
    ].copy()
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame = frame.dropna(subset=["observation_date"]).sort_values("observation_date")
    if frame.empty:
        return {}
    row = frame.iloc[-1]
    return {
        "jet_fuel_observation_date": row["observation_date"].strftime("%Y-%m-%d"),
        "jet_fuel_spot_usd_per_gallon": _num(row["value"]),
    }


def _surcharge_context(company: str) -> dict[str, Any]:
    if not SURCHARGE_PATH.exists():
        return {}
    frame = pd.read_parquet(SURCHARGE_PATH)
    if company == "Cathay Pacific":
        rows = frame.loc[frame["carrier_scope"].eq("Cathay Pacific")]
        if rows.empty:
            return {}
        values = [
            f"{row.current_value:g} {row.currency} ({row.route_band})"
            for row in rows.itertuples()
        ]
        row = rows.sort_values("effective_from").iloc[-1]
        return {
            "surcharge_effective_from": row["effective_from"],
            "surcharge_reference": "; ".join(values),
            "surcharge_source_url": row["source_url"],
        }
    rows = frame.loc[
        (frame["carrier_scope"] == "Mainland China passenger airlines")
        & frame["route_band"].isin(["up to 800 km", ">800 km"])
    ]
    if rows.empty:
        return {}
    row = rows.sort_values("effective_from").iloc[-1]
    values = [
        f"{r.current_value:g} {r.currency} ({r.route_band})"
        for r in rows.itertuples()
    ]
    return {
        "surcharge_effective_from": row["effective_from"],
        "surcharge_reference": "; ".join(values),
        "surcharge_source_url": row["source_url"],
    }


def _fx_snapshot(native_currency: str) -> dict[str, Any]:
    """Return the latest ECB quote needed to translate native values to USD."""
    if not FX_PATH.exists():
        return {}
    pair = "USD_HKD" if native_currency == "HKD" else "USD_CNY"
    frame = pd.read_parquet(FX_PATH)
    frame = frame.loc[frame["pair"].eq(pair)].copy()
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame = frame.dropna(subset=["observation_date", "value"]).sort_values("observation_date")
    if frame.empty:
        return {}
    row = frame.iloc[-1]
    return {
        "fx_pair": pair,
        "fx_observation_date": row["observation_date"].strftime("%Y-%m-%d"),
        "fx_value_quote_per_usd": _num(row["value"]),
    }


def _issuer_sensitivity(company: str, official: pd.DataFrame) -> tuple[float | None, float | None, Any]:
    rows = official.loc[
        official["company"].eq(company)
        & official["report_type"].eq("annual")
        & official["statement_period"].eq("FY2025")
    ]
    if rows.empty:
        return None, None, None
    up = rows.loc[rows["metric"].eq("fuel_price_sensitivity_5pct_profit_if_price_up")]
    down = rows.loc[rows["metric"].eq("fuel_price_sensitivity_5pct_profit_if_price_down")]
    absolute = rows.loc[rows["metric"].eq("fuel_cost_sensitivity_5pct_abs")]
    page = rows.loc[rows["metric"].isin([
        "fuel_price_sensitivity_5pct_profit_if_price_up",
        "fuel_cost_sensitivity_5pct_abs",
    ]), "source_page"]
    source_page = page.iloc[0] if not page.empty else None
    if not up.empty and not down.empty:
        return _num(up.iloc[0]["value_native"]), _num(down.iloc[0]["value_native"]), source_page
    if not absolute.empty:
        value = abs(_num(absolute.iloc[0]["value_native"]) or 0.0)
        return -value, value, source_page
    return None, None, None


def build_fuel_sensitivity_scenarios(
    *,
    bridge: pd.DataFrame | None = None,
    official: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    official = official if official is not None else pd.read_csv(OFFICIAL_PATH)
    energy = _energy_snapshot()
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    # A/H rows share the same underlying financial base; keep one scenario set
    # per company and expose the first available H/A ticker as its reference.
    for company, group in bridge.groupby("company", sort=True):
        item = group.iloc[0]
        fuel_cost = _num(item.get("latest_report_fuel_cost_native_mn"))
        if fuel_cost is None:
            continue
        reported_up, reported_down, source_page = _issuer_sensitivity(company, official)
        surcharge = _surcharge_context(company)
        native_currency = item["price_currency"] if company == "Cathay Pacific" else "RMB"
        fx = _fx_snapshot(native_currency)
        fx_value = _num(fx.get("fx_value_quote_per_usd"))
        fuel_cost_usd = fuel_cost / fx_value if fx_value else None
        for shock in SCENARIOS:
            shock_fraction = shock / 100.0
            if reported_up is not None and reported_down is not None and shock in (-5.0, 5.0):
                impact = reported_up if shock == 5.0 else reported_down
                method = "issuer_reported_5pct_sensitivity"
                quality = "primary_issuer"
            else:
                impact = -fuel_cost * shock_fraction
                method = "mechanical_fuel_cost_proxy"
                quality = "derived_scenario"
            rows.append({
                "dataset_id": "airline_fuel_sensitivity_scenarios",
                "company": company,
                "primary_market_ticker": item["market_ticker"],
                "baseline_period": item["latest_financial_period"],
                "native_currency": native_currency,
                "fuel_cost_native_mn": fuel_cost,
                "fuel_cost_share_pct": _num(item.get("latest_report_fuel_cost_share_pct")),
                "scenario_fuel_price_change_pct": shock,
                "post_shock_fuel_cost_native_mn": fuel_cost * (1.0 + shock_fraction),
                "pre_tax_profit_impact_native_mn": impact,
                "scenario_method": method,
                "issuer_sensitivity_available": reported_up is not None and reported_down is not None,
                "issuer_sensitivity_source_page": source_page,
                **energy,
                **fx,
                "jet_fuel_spot_native_per_gallon": (
                    energy.get("jet_fuel_spot_usd_per_gallon") * fx_value
                    if energy.get("jet_fuel_spot_usd_per_gallon") is not None and fx_value
                    else None
                ),
                "fuel_cost_usd_mn": fuel_cost_usd,
                "post_shock_fuel_cost_usd_mn": (
                    fuel_cost * (1.0 + shock_fraction) / fx_value if fx_value else None
                ),
                "pre_tax_profit_impact_usd_mn": impact / fx_value if fx_value else None,
                **surcharge,
                "source_quality": quality,
                "source_note": (
                    "Issuer sensitivity is used only where the FY2025 report disclosed a 5% fuel-price case. "
                    "Other shocks are mechanical fuel-cost proxies and exclude hedging, fuel mix, contracts, "
                    "pass-through, surcharge recovery, FX and demand response. "
                    "USD fields use the latest point-in-time ECB quote and are not a forward-FX assumption."
                ),
                "retrieved_at": retrieved,
            })
    return pd.DataFrame(rows, columns=SCENARIO_COLUMNS)


def fetch_fuel_sensitivity_scenarios() -> pd.DataFrame:
    result = build_fuel_sensitivity_scenarios()
    result.to_csv(NORMALIZED_DIR / "airline_fuel_sensitivity_scenarios.csv", index=False)
    return result


def source_path() -> Path:
    return NORMALIZED_DIR / "airline_fuel_sensitivity_scenarios.csv"
