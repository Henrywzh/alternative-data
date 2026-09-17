"""Official BLS component snapshots and event-actual verification."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Iterable

import pandas as pd
import requests

from ..config import BLS_COMPONENT_SERIES
from ..domain import component_observation_signature, component_snapshot_id, numeric, payload_checksum
from .http import retrying_session


BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}


def _period_date(year: Any, period: Any) -> pd.Timestamp | None:
    text = str(period or "")
    if not text.startswith("M") or text == "M13":
        return None
    try:
        return pd.Timestamp(year=int(year), month=int(text[1:]), day=1)
    except (TypeError, ValueError):
        return None


def _series_metrics(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    parsed: list[tuple[pd.Timestamp, float]] = []
    for row in rows:
        stamp = _period_date(row.get("year"), row.get("period"))
        value = numeric(row.get("value"))
        if stamp is not None and value is not None:
            parsed.append((stamp, value))
    parsed.sort(key=lambda item: item[0])
    if not parsed:
        return None
    latest_date, latest = parsed[-1]
    previous = parsed[-2][1] if len(parsed) >= 2 else None
    year_ago_target = latest_date - pd.DateOffset(years=1)
    year_ago = next(
        (value for stamp, value in parsed if stamp == year_ago_target),
        None,
    )
    return {
        "reference_period": latest_date.strftime("%Y-%m"),
        "latest_value": latest,
        "previous_value": previous,
        "mom_change": None if previous is None else latest - previous,
        "mom_pct": None if previous in (None, 0) else (latest / previous - 1) * 100,
        "yoy_change": None if year_ago is None else latest - year_ago,
        "yoy_pct": None if year_ago in (None, 0) else (latest / year_ago - 1) * 100,
    }


def _event_reference_month(event: pd.Series) -> str | None:
    """Normalize a calendar's monthly label to the release year's YYYY-MM."""
    value = str(event.get("reference_period") or "").strip()
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if not pd.isna(parsed):
        return parsed.strftime("%Y-%m")
    match = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
        value,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    scheduled = pd.to_datetime(event.get("scheduled_at_utc"), errors="coerce", utc=True)
    if pd.isna(scheduled):
        return None
    month = _MONTHS[match.group(1).casefold()]
    return f"{scheduled.year:04d}-{month:02d}"


def fetch_official_components(
    *,
    trigger_type: str,
    session: requests.Session | None = None,
    now_utc: datetime | None = None,
    timeout: int = 25,
    series_specs: Iterable[dict[str, str]] = BLS_COMPONENT_SERIES,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    retrieved = now_utc or datetime.now(timezone.utc)
    specs = tuple(series_specs)
    start_year = retrieved.year - 1
    payload: dict[str, Any] = {
        "seriesid": [spec["series_id"] for spec in specs],
        "startyear": str(start_year),
        "endyear": str(retrieved.year),
    }
    client = session or retrying_session()
    response = client.post(BLS_URL, json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    if body.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError("BLS API did not report REQUEST_SUCCEEDED")
    returned = {
        str(row.get("seriesID")): row.get("data", [])
        for row in body.get("Results", {}).get("series", [])
        if isinstance(row, dict)
    }
    rows: list[dict[str, Any]] = []
    for spec in specs:
        metrics = _series_metrics(returned.get(spec["series_id"], []))
        if metrics is None:
            continue
        row = {
            **spec,
            **metrics,
            "source_id": "official_bls",
            "source_url": f"https://data.bls.gov/timeseries/{spec['series_id']}",
            "retrieved_at_utc": retrieved.isoformat(),
            "trigger_type": trigger_type,
            "verification_status": "official",
            "payload_checksum": payload_checksum(returned.get(spec["series_id"], [])),
        }
        if spec.get("value_kind") == "payroll_level":
            row["payroll_change"] = row["mom_change"]
            row["mom_pct"] = None
        elif spec.get("value_kind") == "rate":
            row["mom_change_pp"] = row["mom_change"]
            row["yoy_change_pp"] = row["yoy_change"]
            row["mom_pct"] = None
            row["yoy_pct"] = None
        row["observation_signature"] = component_observation_signature(row)
        row["snapshot_id"] = component_snapshot_id(row)
        rows.append(row)
    frame = pd.DataFrame(rows)
    health = {
        "source_id": "official_bls",
        "status": "Healthy" if len(frame) == len(specs) else "Partial" if not frame.empty else "Unavailable",
        "retrieved_at_utc": retrieved.isoformat(),
        "records": int(len(frame)),
        "notes": f"Official BLS component coverage {len(frame)}/{len(specs)}.",
    }
    return frame, health


def _official_metric_for_event(
    event: pd.Series,
    components: pd.DataFrame,
) -> tuple[float | None, str | None, str | None]:
    title = str(event.get("title") or "").casefold()
    if str(event.get("country") or "").upper() != "US":
        return None, None, None
    family = str(event.get("event_family") or "")
    component_id: str | None = None
    metric: str | None = None
    if family == "cpi":
        component_id = "core" if "core" in title else "headline"
        metric = "mom_pct" if "mom" in title else "yoy_pct" if "yoy" in title else None
    elif family == "ppi":
        if "ex food" in title or "less food" in title or "core" in title:
            component_id = "core"
        elif "final demand goods" in title or "final-demand goods" in title:
            component_id = "final_goods"
        elif "final demand services" in title or "final-demand services" in title:
            component_id = "final_services"
        else:
            component_id = "headline"
        metric = (
            "mom_pct"
            if "mom" in title
            else "yoy_pct"
            if "yoy" in title
            else "latest_value"
        )
    elif family in {"payrolls", "labour"}:
        if "non farm payroll" in title or "nonfarm payroll" in title:
            component_id, metric = "headline", "payroll_change"
        elif "unemployment rate" in title:
            component_id, metric = "unemployment", "latest_value"
        elif "participation rate" in title:
            component_id, metric = "participation", "latest_value"
        elif "average hourly earnings" in title:
            component_id = "wages"
            metric = "mom_pct" if "mom" in title else "yoy_pct" if "yoy" in title else "latest_value"
    if component_id is None or metric is None:
        return None, None, None
    subset = components[
        components["component_id"].astype(str).eq(component_id)
        & components["event_family"].astype(str).eq("payrolls" if family == "labour" else family)
    ]
    if subset.empty:
        return None, None, None
    row = subset.iloc[0]
    expected_period = _event_reference_month(event)
    observed_period = str(row.get("reference_period") or "")
    if expected_period is None or observed_period != expected_period:
        # The component frame is intentionally compact/latest-only. Do not
        # compare an event with a newer BLS observation or an unknown period.
        return None, None, None
    return numeric(row.get(metric)), str(row.get("series_id")), str(row.get("reference_period"))


def verify_calendar_actuals(
    events: pd.DataFrame,
    components: pd.DataFrame,
) -> pd.DataFrame:
    """Cross-check supported third-party actuals against official BLS values."""
    if events is None or events.empty or components is None or components.empty:
        return events
    output = events.copy()
    official_values: list[float | None] = []
    official_series: list[str | None] = []
    official_periods: list[str | None] = []
    statuses: list[str] = []
    for _, event in output.iterrows():
        official, series_id, period = _official_metric_for_event(event, components)
        actual = numeric(event.get("actual"))
        status = str(event.get("verification_status") or "third_party_consensus")
        # A latest BLS component is not the actual for a future calendar
        # release.  Keep it out of the event row until the provider reports an
        # actual; the component tab already shows the latest official level.
        if actual is None:
            official = None
            series_id = None
            period = None
        if official is None and status.startswith("official_"):
            status = (
                "third_party_actual_unverified"
                if actual is not None
                else "third_party_consensus"
            )
        if official is not None:
            if actual is None:
                status = "official_component_available"
            else:
                tolerance = 2.0 if series_id == "CES0000000001" else 0.11
                status = (
                    "official_verified"
                    if abs(actual - official) <= tolerance
                    else "official_mismatch"
                )
        official_values.append(official)
        official_series.append(series_id)
        official_periods.append(period)
        statuses.append(status)
    output["official_value"] = official_values
    output["official_series_id"] = official_series
    output["official_reference_period"] = official_periods
    output["verification_status"] = statuses
    return output
