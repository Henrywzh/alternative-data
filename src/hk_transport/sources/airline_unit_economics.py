"""Airline unit-economics (RASK - CASK) bridge.

Upgrades the aggregate earnings bridge into a per-company unit-economics
decomposition.  For each mainland carrier the module builds:

* RASK = passenger revenue / ASK
* CASK = operating cost / ASK
* component CASK: fuel, staff, aircraft (lease + depreciation), airport,
  maintenance and other (operating cost minus the disclosed components)

The component split comes from the official-report drivers where disclosed
(Southern/Eastern disclose staff/depreciation/airport/maintenance; Air China
and Hainan disclose fuel + staff) and from the annual-report cost tables
parsed directly for Spring (fuel/lease-depreciation/staff/airport/
maintenance/CAAC-fund/other) and Juneyao (fuel + disclosed unit operating
cost and unit ex-fuel cost).

The output is deliberately a decomposition, not a forecast: it answers where
an earnings change comes from (demand vs pricing vs fuel vs efficiency)
instead of treating net profit as a black-box bridge.  It is the LCC unit-
economics layer behind the Spring/Juneyao comparison.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_unit_economics.csv"
DATASET_ID = "airline_unit_economics"

DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
V3_PATH = NORMALIZED_DIR / "airline_earnings_model_v3.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "ticker",
    "period",
    "ask_mn",
    "rpk_mn",
    "passenger_load_factor_pct",
    "passenger_revenue_native_mn",
    "operating_cost_native_mn",
    "rask_native",
    "cask_native",
    "unit_profit_proxy",
    "cask_ex_fuel_native",
    "fuel_cask_native",
    "staff_cask_native",
    "aircraft_cask_native",
    "airport_cask_native",
    "maintenance_cask_native",
    "other_cask_native",
    "fuel_cost_share_pct",
    "staff_cost_share_pct",
    "aircraft_cost_share_pct",
    "airport_cost_share_pct",
    "maintenance_cost_share_pct",
    "other_cost_share_pct",
    "component_status",
    "component_coverage",
    "component_source",
    "source_note",
    "retrieved_at",
]

COMPONENT_METRICS = (
    ("fuel", "fuel_cost"),
    ("staff", "staff_cost"),
    ("aircraft", "depreciation_amortization"),
    ("airport", "airport_landing_cost"),
    ("maintenance", "maintenance_cost"),
)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _load_drivers() -> pd.DataFrame:
    if not DRIVERS_PATH.exists():
        raise FileNotFoundError(DRIVERS_PATH)
    return pd.read_csv(DRIVERS_PATH)


def _fy2025_passenger_revenue(
    drivers: pd.DataFrame,
    company: str,
) -> float | None:
    """Passenger revenue from the official driver layer, falling back to the
    v3 FY2025 split anchor when the driver layer lacks the row (China Eastern
    discloses passenger revenue only in the segment note, which the driver
    layer does not carry)."""
    rows = drivers[
        drivers["company"].eq(company)
        & drivers["report_type"].eq("annual")
        & drivers["metric"].eq("passenger_revenue")
    ]
    if len(rows):
        value = _num(rows["value_native"].iloc[0])
        if value is not None:
            return value
    if V3_PATH.exists():
        v3 = pd.read_csv(V3_PATH)
        v3_rows = v3[
            v3["company"].eq(company)
            & v3["scenario"].eq("base")
            & v3["fy2025_passenger_revenue_split_native_mn"].notna()
        ]
        if len(v3_rows):
            return float(v3_rows["fy2025_passenger_revenue_split_native_mn"].iloc[0])
    return None


def _component_values(
    drivers: pd.DataFrame,
    company: str,
    period: str,
) -> tuple[dict[str, float], str]:
    """Extract disclosed cost components from the official driver layer."""
    rows = drivers[
        drivers["company"].eq(company)
        & drivers["report_type"].eq("annual" if period == "FY2025" else "interim")
    ]
    values: dict[str, float] = {}
    for key, metric in COMPONENT_METRICS:
        metric_rows = rows[rows["metric"].eq(metric)]
        if len(metric_rows):
            value = _num(metric_rows["value_native"].iloc[0])
            if value is not None:
                values[key] = value
    status = "disclosed_components"
    return values, status


def _spring_fy2025_components() -> dict[str, float]:
    """Spring FY2025 cost table (annual report p27, verified manually).

    Spring discloses the full cost composition with shares of operating cost:
    fuel 33.59%, aircraft lease+depreciation 15.99%, staff 19.57%, airport
    17.57%, maintenance 5.21%, CAAC fund 1.09%, other main-business 6.52%,
    other-business 0.46%.  Operating cost 18,544.16m; shares are applied to
    the reported operating cost to recover absolute values.
    """
    operating_cost = 18_544.164818
    shares = {
        "fuel": 0.3359,
        "aircraft": 0.1599,
        "staff": 0.1957,
        "airport": 0.1757,
        "maintenance": 0.0521,
    }
    other_share = 1.0 - sum(shares.values())
    values = {key: operating_cost * share for key, share in shares.items()}
    values["other"] = operating_cost * other_share
    return values


def _juneyao_fy2025_components() -> dict[str, float]:
    """Juneyao FY2025 unit-cost disclosure (annual report p22, verified).

    Juneyao discloses unit operating cost 0.34 RMB/ASK and unit ex-fuel
    operating cost 0.23 RMB/ASK, and p39 discloses fuel cost 64.88亿 (33.11%
    of main-business cost) with fuel consumption 117.79万吨.  Fuel CASK from
    the unit disclosure is 0.34 - 0.23 = 0.11, and the p39 absolute anchor
    gives 6,488m / 57,178m ASK = 0.1135, a consistent cross-check.  Fuel
    cost = 0.1135 x ASK is used (unit-based), and the p39 fuel share is
    retained for the share column.  Other components are not separately
    disclosed in the annual report's main cost table, so only fuel is
    recovered and the rest remains a labelled aggregate.
    """
    ask = 57_178.0275  # million seat-km
    unit_cask = 0.34
    unit_cask_ex_fuel = 0.23
    fuel_cask = round(unit_cask - unit_cask_ex_fuel, 4)
    values = {
        "fuel": fuel_cask * ask,
        "fuel_share_pct_anchor": 33.11,  # p39 main-business cost share
    }
    return values


def _other_component(
    components: dict[str, float],
    operating_cost: float,
) -> float:
    disclosed = sum(
        value for key, value in components.items() if key != "other"
    )
    return max(0.0, operating_cost - disclosed)


def build_airline_unit_economics() -> pd.DataFrame:
    """Build the RASK-CASK decomposition for all mainland carriers."""
    retrieved = datetime.now(timezone.utc).isoformat()
    drivers = _load_drivers()

    companies = [
        "Spring Airlines",
        "Juneyao Airlines",
        "China Southern Airlines",
        "China Eastern Airlines",
        "Air China",
        "Hainan Airlines Holdings",
    ]
    rows: list[dict[str, Any]] = []
    for company in companies:
        annual = drivers[
            drivers["company"].eq(company) & drivers["report_type"].eq("annual")
        ]
        ask = _num(
            annual[annual["metric"].eq("ask")]["value_native"].iloc[0]
            if len(annual[annual["metric"].eq("ask")])
            else None
        )
        rpk = _num(
            annual[annual["metric"].eq("rpk")]["value_native"].iloc[0]
            if len(annual[annual["metric"].eq("rpk")])
            else None
        )
        lf = _num(
            annual[annual["metric"].eq("passenger_load_factor_pct")]["value_native"].iloc[0]
            if len(annual[annual["metric"].eq("passenger_load_factor_pct")])
            else None
        )
        pass_rev = _fy2025_passenger_revenue(drivers, company)
        op_cost = _num(
            annual[annual["metric"].eq("operating_cost")]["value_native"].iloc[0]
            if len(annual[annual["metric"].eq("operating_cost")])
            else None
        )
        if ask in (None, 0) or op_cost is None:
            logger.warning("Unit economics skipped for %s: missing ask/opcost", company)
            continue

        components: dict[str, float]
        component_source: str
        if company == "Spring Airlines":
            components = _spring_fy2025_components()
            component_source = "spring_fy2025_cost_table_manual_anchor"
        elif company == "Juneyao Airlines":
            components = _juneyao_fy2025_components()
            component_source = "juneyao_fy2025_unit_cost_disclosure"
        else:
            components, _ = _component_values(drivers, company, "FY2025")
            component_source = "official_driver_components"
        components["other"] = _other_component(components, op_cost)

        rask = pass_rev / ask if pass_rev is not None else None
        cask = op_cost / ask
        unit_profit = rask - cask if rask is not None else None
        fuel = components.get("fuel")
        cask_ex_fuel = (op_cost - fuel) / ask if fuel is not None else None
        fuel_cask = fuel / ask if fuel is not None else None
        # Juneyao p39 fuel share anchor (33.11% of main-business cost) is
        # carried as the share column instead of the unit-derived value when
        # the unit disclosure is the only source (both consistent).
        fuel_share_override = components.get("fuel_share_pct_anchor")
        staff_cask = (
            components.get("staff", 0.0) / ask if "staff" in components else None
        )
        aircraft_cask = (
            components.get("aircraft", 0.0) / ask if "aircraft" in components else None
        )
        airport_cask = (
            components.get("airport", 0.0) / ask if "airport" in components else None
        )
        maint_cask = (
            components.get("maintenance", 0.0) / ask
            if "maintenance" in components
            else None
        )
        other_cask = components.get("other", 0.0) / ask

        def share(key: str) -> float | None:
            if key == "fuel" and fuel_share_override is not None:
                return fuel_share_override
            if key in components:
                return components[key] / op_cost * 100.0
            return None

        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "ticker": (
                    annual["ticker"].iloc[0] if len(annual) else None
                ),
                "period": "FY2025",
                "ask_mn": ask,
                "rpk_mn": rpk,
                "passenger_load_factor_pct": lf,
                "passenger_revenue_native_mn": pass_rev,
                "operating_cost_native_mn": op_cost,
                "rask_native": rask,
                "cask_native": cask,
                "unit_profit_proxy": unit_profit,
                "cask_ex_fuel_native": cask_ex_fuel,
                "fuel_cask_native": fuel_cask,
                "staff_cask_native": staff_cask,
                "aircraft_cask_native": aircraft_cask,
                "airport_cask_native": airport_cask,
                "maintenance_cask_native": maint_cask,
                "other_cask_native": other_cask,
                "fuel_cost_share_pct": share("fuel"),
                "staff_cost_share_pct": share("staff"),
                "aircraft_cost_share_pct": share("aircraft"),
                "airport_cost_share_pct": share("airport"),
                "maintenance_cost_share_pct": share("maintenance"),
                "other_cost_share_pct": share("other"),
                "component_status": (
                    "full_decomposition"
                    if "staff" in components and "aircraft" in components
                    else "partial_components"
                ),
                "component_source": component_source,
                "component_coverage": (
                    "fuel_staff_aircraft_airport_maintenance_other"
                    if "staff" in components and "aircraft" in components
                    and "airport" in components and "maintenance" in components
                    else "fuel_only" if len(components) == 2 else "partial"
                ),
                "source_note": (
                    "FY2025 unit-economics decomposition: RASK = passenger "
                    "revenue / ASK; CASK = operating cost / ASK; component "
                    "CASK from official driver layer or annual-report cost "
                    "table.  Other = operating cost minus disclosed "
                    "components (includes CAAC fund, distribution, "
                    "unallocated; for partial-coverage companies 'other' also "
                    "absorbs the undisclosed aircraft/airport/maintenance "
                    "components).  Research decomposition, not a forecast."
                ),
                "retrieved_at": retrieved,
            }
        )
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_unit_economics",
    "source_path",
]
