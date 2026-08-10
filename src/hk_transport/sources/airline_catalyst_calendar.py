"""Airline catalyst & risk calendar (priority 7).

Moves the research forward: a dated calendar of events over the next 3-12
months that can move airline earnings, each mapped to the KPI it hits and
the earnings line it feeds:

    Event -> KPI -> Earnings -> Company

Examples: HSR opening -> domestic trunk pricing -> yield -> RASK;
Golden Week -> RPK -> revenue; fuel price reset -> fuel CASK; aircraft
delivery -> ASK; visa policy -> international RPK.

Sources: filing calendar (1H2026 report dates), capacity pipeline (fleet
deliveries / route launches), CAAC seasonal schedule, holiday calendar
(Golden Week / Spring Festival), and the fuel/FX series cadence.  Every
row carries a window, the affected companies, the KPI and earnings link,
and a direction hypothesis.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_catalyst_calendar.csv"
DATASET_ID = "airline_catalyst_calendar"

FILING_CALENDAR_PATH = NORMALIZED_DIR / "airline_filing_calendar.csv"
CAPACITY_PIPELINE_PATH = NORMALIZED_DIR / "airline_capacity_pipeline.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "event_id",
    "event_category",
    "event_name",
    "event_window_start",
    "event_window_end",
    "affected_companies",
    "kpi_link",
    "earnings_link",
    "direction_hypothesis",
    "source",
    "source_quality",
    "source_note",
    "retrieved_at",
]


def _num(value: Any) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _filing_events() -> list[dict[str, Any]]:
    fc = pd.read_csv(FILING_CALENDAR_PATH)
    rows = []
    for _, r in fc.iterrows():
        company = r["company"]
        period = r["statement_period"]
        scheduled = r["first_scheduled_date"]
        if pd.isna(scheduled):
            continue
        rows.append(
            {
                "event_category": "earnings_report",
                "event_name": f"{company} {period} report",
                "event_window_start": scheduled,
                "event_window_end": scheduled,
                "affected_companies": company,
                "kpi_link": "reported ASK/RPK/LF/yield/cargo",
                "earnings_link": "actual revenue/op profit/net income vs pre-event forecast and consensus",
                "direction_hypothesis": (
                    "validation catalyst: tests the pre-event forecast; "
                    "revision trigger for FY26 consensus"
                ),
                "source": "filing_calendar",
                "source_quality": "public_discovery",
            }
        )
    return rows


def _capacity_events() -> list[dict[str, Any]]:
    cp = pd.read_csv(CAPACITY_PIPELINE_PATH)
    rows = []
    for _, r in cp.iterrows():
        company = r["company"]
        category = r["event_category"]
        detail = r["event_detail"]
        if category not in ("fleet_delivery", "route_launch"):
            continue
        rows.append(
            {
                "event_category": category,
                "event_name": f"{company}: {detail[:60]}",
                "event_window_start": r["event_date"],
                "event_window_end": r["event_date"],
                "affected_companies": company,
                "kpi_link": "ASK" if category == "fleet_delivery" else "new route frequency",
                "earnings_link": "capacity -> revenue (ASK x RASK)",
                "direction_hypothesis": (
                    "adds capacity" if r["capacity_impact_direction"] == "add_capacity"
                    else "reduces capacity"
                ),
                "source": "capacity_pipeline",
                "source_quality": r["confidence"],
            }
        )
    return rows


def _holiday_events() -> list[dict[str, Any]]:
    """Recurring mainland travel-demand windows (next 12 months)."""
    return [
        {
            "event_category": "holiday_demand",
            "event_name": "Mid-Autumn Festival travel",
            "event_window_start": "2026-09-25",
            "event_window_end": "2026-10-02",
            "affected_companies": "all mainland carriers",
            "kpi_link": "daily RPK / load factor",
            "earnings_link": "3Q revenue (peak travel)",
            "direction_hypothesis": "positive demand pulse; HSR competes on short-haul",
            "source": "holiday_calendar",
            "source_quality": "official_calendar",
        },
        {
            "event_category": "holiday_demand",
            "event_name": "National Day Golden Week travel",
            "event_window_start": "2026-10-01",
            "event_window_end": "2026-10-08",
            "affected_companies": "all mainland carriers",
            "kpi_link": "daily RPK / load factor",
            "earnings_link": "3Q revenue",
            "direction_hypothesis": "largest domestic demand window; yield test",
            "source": "holiday_calendar",
            "source_quality": "official_calendar",
        },
        {
            "event_category": "holiday_demand",
            "event_name": "2027 Spring Festival transport (40-day)",
            "event_window_start": "2027-01-25",
            "event_window_end": "2027-03-05",
            "affected_companies": "all mainland carriers",
            "kpi_link": "40-day passenger flow",
            "earnings_link": "1Q revenue",
            "direction_hypothesis": "peak demand; 2026 baseline +5.7%/day normalized",
            "source": "mot_calendar",
            "source_quality": "official_calendar",
        },
    ]


def _sector_events() -> list[dict[str, Any]]:
    return [
        {
            "event_category": "fuel",
            "event_name": "Monthly jet fuel benchmark + surcharge reviews",
            "event_window_start": "2026-09-01",
            "event_window_end": "2027-08-31",
            "affected_companies": "all carriers",
            "kpi_link": "fuel CASK (driver model)",
            "earnings_link": "operating cost",
            "direction_hypothesis": "2026 spot ~66% above FY25 avg; surcharge pass-through partial",
            "source": "eia_fuel_surcharge",
            "source_quality": "official",
        },
        {
            "event_category": "monthly_kpi",
            "event_name": "Issuer monthly operating releases (each month)",
            "event_window_start": "2026-08-15",
            "event_window_end": "2027-08-10",
            "affected_companies": "all six mainland carriers",
            "kpi_link": "monthly ASK/RPK/LF",
            "earnings_link": "revenue bridge (RPK-ASK gap -> yield pressure)",
            "direction_hypothesis": "track Spring-Juneyao RPK-ASK gap divergence",
            "source": "cninfo_monthly",
            "source_quality": "issuer_primary",
        },
        {
            "event_category": "seasonal_schedule",
            "event_name": "CAAC winter/spring 2026-27 schedule (Oct 2026)",
            "event_window_start": "2026-10-25",
            "event_window_end": "2027-03-27",
            "affected_companies": "all mainland carriers",
            "kpi_link": "planned weekly flights / new routes",
            "earnings_link": "forward ASK (capacity pipeline)",
            "direction_hypothesis": "schedule change resets route mix; watch Spring/Juneyao route counts",
            "source": "caac_seasonal",
            "source_quality": "official",
        },
    ]


def build_airline_catalyst_calendar() -> pd.DataFrame:
    """Build the forward catalyst & risk calendar."""
    retrieved = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for i, event in enumerate(
        _filing_events() + _capacity_events() + _holiday_events() + _sector_events()
    ):
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "event_id": f"cat_{i:03d}",
                **event,
                "source_note": (
                    "Catalyst & risk calendar: event -> KPI -> earnings -> "
                    "company chain.  Windows are scheduled/projected; the "
                    "earnings link is a direction hypothesis, not a forecast."
                ),
                "retrieved_at": retrieved,
            }
        )
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result = result.sort_values(["event_window_start", "event_category"]).reset_index(drop=True)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_catalyst_calendar",
    "source_path",
]
