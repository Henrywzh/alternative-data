"""Airline future capacity pipeline (fleet / route / utilisation / slots).

Upgrades the static fleet snapshot into a forward capacity view: what will
change ASK over the next 6-24 months and why.  Following the MTR project
pipeline logic, the module builds dated future events per carrier:

* fleet deliveries / retirements: on-order book from the Wikipedia fleet
  snapshot, anchored to each carrier's realised delivery pace over the
  trailing 12 months (from the operating-events layer) and its disclosed
  fleet-total trajectory in 2026 H1;
* route launches: CAAC 2026 summer/autumn new-route licences with planned
  start dates and initial weekly frequency;
* utilisation: CAAC sector monthly aircraft-utilisation trend;
* slot/season: CAAC seasonal schedule context (planned weekly flights).

Output is a dated event table plus a per-carrier ASK growth decomposition:

    ASK_{t+h} ~ ASK_t + fleet growth + utilisation + route mix + slot changes

The decomposition is deliberately approximate and labelled; it is a forward
investment-thesis input (why capacity will change), not a fitted forecast.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from ..config import NORMALIZED_DIR, ROOT_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_capacity_pipeline.csv"
DATASET_ID = "airline_capacity_pipeline"

FLEET_SNAPSHOT_PATH = NORMALIZED_DIR / "airline_fleet_wikipedia_snapshot.csv"
CAAC_ROUTE_LICENCE_PATH = NORMALIZED_DIR / "airline_caac_route_licence_events.csv"
CAAC_PATH = NORMALIZED_DIR / "airline_caac_sector_monthly.csv"
OPERATING_EVENTS_PATH = (
    ROOT_DIR / "data" / "processed" / "airline_traffic"
    / "china_airlines_operating_events.parquet"
)
MONTHLY_RAW_PATH = (
    ROOT_DIR / "data" / "processed" / "airline_traffic"
    / "china_airlines_monthly.parquet"
)

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "event_date",
    "horizon",
    "event_category",
    "event_detail",
    "capacity_impact_direction",
    "capacity_impact_units",
    "confidence",
    "source",
    "source_note",
    "retrieved_at",
]

COMPANY_CODE_MAP = {
    "Air China": "601111",
    "China Southern Airlines": "600029",
    "China Eastern Airlines": "600115",
    "Hainan Airlines Holdings": "600221",
    "Spring Airlines": "601021",
    "Juneyao Airlines": "603885",
}

# Delivery-window assumption: on-order aircraft are delivered over roughly 3
# years at a steady pace; the trailing-12m net-add is used as the observed
# pace anchor and capped by the remaining order book.
DELIVERY_WINDOW_MONTHS = 36

# How many trailing-12m net aircraft adds it takes to call an observed delivery
# pace credible.  These are thresholds on a *rate*, not on the sign of the
# number: Juneyao took one aircraft and retired none over a year on a fleet of
# 130, and a strictly-positive test would read that single airframe as evidence
# of a delivery cadence and stamp the forward projection "medium".  One
# observation is not a pace, so the floor sits above it.
MEDIUM_CONFIDENCE_NET_ADDS = 2
HIGH_CONFIDENCE_NET_ADDS = 5


def _num(value: Any) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _load_fleet_snapshot() -> pd.DataFrame:
    if not FLEET_SNAPSHOT_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(FLEET_SNAPSHOT_PATH)


def _load_route_licences() -> pd.DataFrame:
    if not CAAC_ROUTE_LICENCE_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(CAAC_ROUTE_LICENCE_PATH)


def _load_caac() -> pd.DataFrame:
    if not CAAC_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(CAAC_PATH)


def _load_operating_events() -> pd.DataFrame:
    if not OPERATING_EVENTS_PATH.exists():
        return pd.DataFrame()
    return pq.read_table(OPERATING_EVENTS_PATH).to_pandas()


def _load_monthly() -> pd.DataFrame:
    if not MONTHLY_RAW_PATH.exists():
        return pd.DataFrame()
    return pq.read_table(MONTHLY_RAW_PATH).to_pandas()


def _trailing_net_fleet_add(
    events: pd.DataFrame,
    code: str,
    *,
    months: int = 12,
) -> float:
    if events.empty:
        return 0.0
    events = events.copy()
    events["month_parsed"] = pd.to_datetime(events["month"], errors="coerce")
    cutoff = pd.Timestamp.now() - pd.DateOffset(months=months)
    sub = events[
        events["airline_code"].eq(code)
        & events["month_parsed"].ge(cutoff)
    ]
    added = sub[sub["event_type"].eq("fleet_added_aircraft")]["value"].sum()
    retired = sub[sub["event_type"].eq("fleet_retired_aircraft")]["value"].sum()
    return float(added - retired)


def _fleet_delivery_events(
    snapshot: pd.DataFrame,
    events: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if snapshot.empty or "on_order" not in snapshot.columns:
        return rows
    snapshot = snapshot.copy()
    snapshot["on_order_num"] = pd.to_numeric(snapshot["on_order"], errors="coerce")
    today = pd.Timestamp.now().normalize()
    for company, group in snapshot.groupby("company"):
        if company not in COMPANY_CODE_MAP:
            continue
        code = COMPANY_CODE_MAP[company]
        order_total = float(group["on_order_num"].sum(min_count=1) or 0.0)
        if order_total <= 0:
            continue
        trailing = _trailing_net_fleet_add(events, code)
        pace = max(trailing, 0.0)  # observed annualised pace
        # If no observed pace, assume steady delivery over the window.
        annual_delivery = pace if pace > 0 else order_total / (DELIVERY_WINDOW_MONTHS / 12)
        annual_delivery = min(annual_delivery, order_total)  # cannot exceed book
        for horizon_months, label in ((6, "6m"), (12, "12m"), (24, "24m")):
            expected = min(annual_delivery * horizon_months / 12, order_total)
            if expected < 0.5:
                continue
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "company": company,
                    "event_date": (today + pd.DateOffset(months=horizon_months)).strftime("%Y-%m-%d"),
                    "horizon": label,
                    "event_category": "fleet_delivery",
                    "event_detail": (
                        f"on-order {order_total:.0f} aircraft; observed "
                        f"trailing-12m net add {trailing:.0f}; expected "
                        f"deliveries ~{expected:.0f} over {label}"
                    ),
                    "capacity_impact_direction": "add_capacity",
                    "capacity_impact_units": "aircraft",
                    "confidence": (
                        "high"
                        if trailing >= HIGH_CONFIDENCE_NET_ADDS
                        else "medium"
                        if trailing >= MEDIUM_CONFIDENCE_NET_ADDS
                        else "low_no_recent_delivery_pace"
                    ),
                    "source": "wikipedia_fleet_on_order + operating_events_delivery_pace",
                    "source_note": (
                        "On-order book from Wikipedia fleet snapshot, "
                        "delivery pace anchored to trailing-12m observed net "
                        "fleet add; assumes steady delivery, capped by "
                        "remaining book.  Approximate forward capacity input, "
                        "not a firm delivery schedule."
                    ),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
            )
    return rows


def _route_launch_events(
    route_licences: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if route_licences.empty:
        return rows
    new_routes = route_licences[
        route_licences["table_type"].eq("new_domestic_route")
    ]
    for company, group in new_routes.groupby("airline_normalized_name"):
        if company not in COMPANY_CODE_MAP:
            continue
        route_count = int(len(group))
        weekly_freq = float(
            pd.to_numeric(group["initial_frequency_per_week"], errors="coerce").sum(min_count=1)
            or 0.0
        )
        start_dates = group["planned_start_date"].dropna().unique()
        start = start_dates[0] if len(start_dates) else "2026_summer_schedule"
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "event_date": start,
                "horizon": "2026_summer_autumn",
                "event_category": "route_launch",
                "event_detail": (
                    f"{route_count} new domestic routes, ~{weekly_freq:.0f} "
                    f"weekly initial frequency"
                ),
                "capacity_impact_direction": "add_capacity",
                "capacity_impact_units": "weekly_frequency",
                "confidence": "high_licence_issued",
                "source": "caac_2026_summer_autumn_route_licence_table",
                "source_note": (
                    "Planned supply events from the CAAC seasonal licence "
                    "table; licence issuance does not guarantee operation at "
                    "initial frequency."
                ),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return rows


def _utilisation_events(caac: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if caac.empty or "metric" not in caac.columns:
        return rows
    util = caac[
        caac["metric"].eq("aircraft_daily_utilization")
        & caac["period_type"].eq("monthly")
        & caac["scope"].eq("total")
    ].copy()
    util["month_parsed"] = pd.to_datetime(
        util["observation_month"].astype(str) + "-01", errors="coerce"
    )
    util = util.sort_values("month_parsed")
    if len(util) < 13:
        return rows
    latest = util.iloc[-1]
    prior = util.iloc[-13]
    change = float(latest["value"]) - float(prior["value"])
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "company": "industry",
            "event_date": latest["observation_month"],
            "horizon": "trailing_12m",
            "event_category": "utilisation_trend",
            "event_detail": (
                f"CAAC sector daily utilisation {float(prior['value']):.1f}h "
                f"-> {float(latest['value']):.1f}h ({change:+.1f}h YoY)"
            ),
            "capacity_impact_direction": (
                "add_capacity" if change > 0 else "reduce_capacity"
            ),
            "capacity_impact_units": "hours_per_day",
            "confidence": "high_official",
            "source": "caac_sector_monthly",
            "source_note": (
                "Sector-wide daily utilisation trend; company utilisation "
                "varies by fleet and network."
            ),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return rows


def _trailing_12m_growth_pct(sub: pd.DataFrame) -> float | None:
    """Growth of the last twelve months against the twelve before them.

    Deliberately *not* the latest month against the same month a year ago.
    Chinese carriers publish one traffic print a month and single-month ASK
    YoY swings violently with the timing of Spring Festival, a typhoon week or
    a single wet-lease: Spring Airlines' last six monthly prints ran +22.7,
    +22.9, +12.6, +15.0, +15.9, +8.0.  Reading whichever month happens to be
    last therefore lands anywhere in a 15pp band, and the downstream pair
    spread inherits all of it.  Summing both twelve-month windows keeps the
    figure the field name already promises.

    Returns ``None`` when the carrier has not published two clean consecutive
    years, so a partly-covered carrier is dropped rather than compared against
    a short window.
    """
    if sub.empty:
        return None
    months = sub["month_parsed"]
    if months.isna().any():
        return None
    latest_month = months.max()
    windows = []
    for offset in (0, 12):
        end = latest_month - pd.DateOffset(months=offset)
        start = end - pd.DateOffset(months=11)
        window = sub[months.ge(start) & months.le(end)]
        values = pd.to_numeric(window["value"], errors="coerce")
        if len(window) != 12 or values.isna().any():
            return None
        windows.append(float(values.sum()))
    trailing, prior = windows
    if prior <= 0:
        return None
    return (trailing / prior - 1.0) * 100.0


def _ask_decomposition(
    monthly: pd.DataFrame,
    snapshot: pd.DataFrame,
    events: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Per-carrier ASK growth decomposition for the forward horizon."""
    rows: list[dict[str, Any]] = []
    if monthly.empty:
        return rows
    monthly = monthly.copy()
    monthly["month_parsed"] = pd.to_datetime(monthly["month"], errors="coerce")
    ask = monthly[
        monthly["region"].eq("Total") & monthly["metric"].eq("ask")
    ]
    today = pd.Timestamp.now().normalize()
    for company, code in COMPANY_CODE_MAP.items():
        sub = ask[ask["airline_code"].eq(code)].sort_values("month_parsed")
        ask_growth = _trailing_12m_growth_pct(sub)
        if ask_growth is None:
            continue
        fleet_growth = 0.0
        if not snapshot.empty:
            fleet_rows = snapshot[snapshot["company"].eq(company)]
            order_total = float(
                pd.to_numeric(fleet_rows["on_order"], errors="coerce").sum(min_count=1)
                or 0.0
            )
            trailing = _trailing_net_fleet_add(events, code)
            fleet_growth = min(
                max(trailing, 0.0),
                order_total,
            )
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "event_date": today.strftime("%Y-%m-%d"),
                "horizon": "ask_decomposition_trailing_12m",
                "event_category": "ask_decomposition",
                "event_detail": (
                    f"trailing-12m ASK growth {ask_growth:+.1f}%; forward "
                    f"fleet pipeline ~{fleet_growth:.0f} aircraft; route "
                    f"licences and utilisation in separate rows"
                ),
                "capacity_impact_direction": (
                    "add_capacity" if ask_growth > 0 else "reduce_capacity"
                ),
                "capacity_impact_units": "percent",
                "confidence": "high_observed",
                "source": "issuer_monthly_ask + fleet_pipeline",
                "source_note": (
                    "Trailing-12m ASK growth is observed; the fleet pipeline "
                    "is the estimated forward add.  Route-mix and slot "
                    "changes are qualitative modifiers from the CAAC licence "
                    "and seasonal layers."
                ),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return rows


def build_airline_capacity_pipeline() -> pd.DataFrame:
    """Build the forward capacity pipeline and ASK decomposition."""
    retrieved = datetime.now(timezone.utc).isoformat()
    snapshot = _load_fleet_snapshot()
    route_licences = _load_route_licences()
    caac = _load_caac()
    events = _load_operating_events()
    monthly = _load_monthly()

    rows: list[dict[str, Any]] = []
    rows.extend(_fleet_delivery_events(snapshot, events))
    rows.extend(_route_launch_events(route_licences))
    rows.extend(_utilisation_events(caac))
    rows.extend(_ask_decomposition(monthly, snapshot, events))
    for row in rows:
        if row.get("retrieved_at") is None:
            row["retrieved_at"] = retrieved

    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result = result.sort_values(["company", "event_date", "event_category"]).reset_index(drop=True)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_capacity_pipeline",
    "source_path",
]
