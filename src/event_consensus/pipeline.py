"""Calendar, consensus and cross-asset snapshot orchestration."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .config import (
    COMPONENT_CONTRACTS,
    DEFAULT_COUNTRIES,
    DEFAULT_LOOKAHEAD_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    LATEST_ARTIFACT_PATH,
    MARKET_INSTRUMENTS,
    REPO_ROOT,
    SCENARIO_TEMPLATES,
    SCHEMA_VERSION,
)
from .credentials import resolve_credential
from .domain import enrich_event_row
from .sources.finnhub import fetch_quotes
from .sources.bls import fetch_official_components, verify_calendar_actuals
from .sources.futu import fetch_futu_quotes
from .sources.tradingview import fetch_calendar
from .storage import (
    append_component_snapshots,
    append_event_snapshots,
    append_quote_snapshots,
    load_artifact,
    load_component_ledger,
    load_event_ledger,
    load_quote_ledger,
    save_artifact,
)


def _date(value: date | str | None, fallback: date) -> date:
    if value is None:
        return fallback
    return pd.Timestamp(value).date()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    clean = frame.astype(object).where(pd.notna(frame), None)
    return clean.to_dict("records")


def _latest_per_event(frame: pd.DataFrame) -> pd.DataFrame:
    if (
        frame is None
        or frame.empty
        or "event_id" not in frame.columns
        or "scheduled_at_utc" not in frame.columns
    ):
        return pd.DataFrame()
    output = frame.copy()
    output["_retrieved"] = pd.to_datetime(
        output.get("retrieved_at_utc"),
        errors="coerce",
        utc=True,
    )
    return (
        output.sort_values(["event_id", "_retrieved"])
        .drop_duplicates("event_id", keep="last")
        .drop(columns="_retrieved")
        .sort_values(["scheduled_at_utc", "risk_score"], ascending=[True, False])
        .reset_index(drop=True)
    )


def _timestamp_minimum(*values: Any) -> str | None:
    parsed: list[pd.Timestamp] = []
    for value in values:
        stamp = pd.to_datetime(value, errors="coerce", utc=True)
        if not pd.isna(stamp):
            parsed.append(stamp)
    return min(parsed).isoformat() if parsed else None


def _with_first_observed(
    events: pd.DataFrame,
    *,
    event_ledger: pd.DataFrame,
    previous_artifact: dict[str, Any] | None,
) -> pd.DataFrame:
    """Carry the first-seen timestamp forward without mutating old rows."""
    if events is None or events.empty or "event_id" not in events.columns:
        return events
    first_seen: dict[str, str] = {}
    sources = [
        event_ledger,
        pd.DataFrame(previous_artifact.get("events", []))
        if previous_artifact
        else pd.DataFrame(),
    ]
    for source in sources:
        if source is None or source.empty or "event_id" not in source.columns:
            continue
        for row in source.to_dict(orient="records"):
            event_id = str(row.get("event_id") or "")
            if not event_id:
                continue
            candidate = _timestamp_minimum(
                row.get("first_observed_at_utc"),
                row.get("retrieved_at_utc"),
            )
            if candidate is not None:
                first_seen[event_id] = _timestamp_minimum(
                    first_seen.get(event_id), candidate
                ) or candidate
    output = events.copy()
    output["first_observed_at_utc"] = [
        _timestamp_minimum(
            first_seen.get(str(row.get("event_id") or "")),
            row.get("first_observed_at_utc"),
            row.get("retrieved_at_utc"),
        )
        for row in output.to_dict(orient="records")
    ]
    return output


def _merge_retained_events(
    current: pd.DataFrame,
    previous_artifact: dict[str, Any] | None,
    *,
    start: date,
    end: date,
    now_utc: datetime,
) -> tuple[pd.DataFrame, int]:
    """Keep prior window rows absent from a partial provider response."""
    if current is None or current.empty or not previous_artifact:
        return current, 0
    previous = pd.DataFrame(previous_artifact.get("events", []))
    if (
        previous.empty
        or "event_id" not in previous.columns
        or "scheduled_at_utc" not in previous.columns
    ):
        return current, 0
    scheduled = pd.to_datetime(previous.get("scheduled_at_utc"), errors="coerce", utc=True)
    previous = previous.loc[scheduled.dt.date.between(start, end)].copy()
    if previous.empty:
        return current, 0
    current_ids = set(current["event_id"].astype(str)) if "event_id" in current.columns else set()
    retained = previous[~previous["event_id"].astype(str).isin(current_ids)].copy()
    if retained.empty:
        return current, 0
    retained = pd.DataFrame(
        [enrich_event_row(row, now_utc=now_utc) for row in retained.to_dict(orient="records")]
    )
    retained["fallback_status"] = "retained_last_valid_artifact"
    combined = pd.DataFrame(
        [*current.to_dict(orient="records"), *retained.to_dict(orient="records")]
    )
    return _latest_per_event(combined), int(len(retained))


def _annotate_retained(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return frame
    output = frame.copy()
    output["fallback_status"] = "retained_last_valid_artifact"
    return output


def _merge_retained_by_key(
    current: pd.DataFrame,
    retained: pd.DataFrame,
    *,
    key: str,
) -> pd.DataFrame:
    if retained is None or retained.empty:
        return current
    if current is None or current.empty or key not in current.columns or key not in retained.columns:
        return current if current is not None and not current.empty else _annotate_retained(retained)
    current_keys = set(current[key].astype(str))
    missing = retained[~retained[key].astype(str).isin(current_keys)].copy()
    if missing.empty:
        return current
    return pd.DataFrame(
        [*current.to_dict(orient="records"), *_annotate_retained(missing).to_dict(orient="records")]
    )


def _bounded_history(
    ledger: pd.DataFrame,
    event_ids: set[str],
    *,
    per_event: int = 20,
) -> pd.DataFrame:
    if (
        ledger is None
        or ledger.empty
        or not event_ids
        or "event_id" not in ledger.columns
        or "retrieved_at_utc" not in ledger.columns
    ):
        return pd.DataFrame()
    history = ledger[ledger["event_id"].astype(str).isin(event_ids)].copy()
    history["_retrieved"] = pd.to_datetime(
        history.get("retrieved_at_utc"),
        errors="coerce",
        utc=True,
    )
    return (
        history.sort_values(["event_id", "_retrieved"])
        .groupby("event_id", group_keys=False)
        .tail(per_event)
        .drop(columns="_retrieved")
        .reset_index(drop=True)
    )


def _fallback_events(
    previous_artifact: dict[str, Any] | None,
    *,
    start: date,
    end: date,
    now_utc: datetime,
) -> pd.DataFrame:
    if not previous_artifact:
        return pd.DataFrame()
    frame = pd.DataFrame(previous_artifact.get("events", []))
    if frame.empty or "scheduled_at_utc" not in frame.columns:
        return pd.DataFrame()
    scheduled = pd.to_datetime(frame["scheduled_at_utc"], errors="coerce", utc=True)
    mask = scheduled.dt.date.between(start, end)
    output = frame.loc[mask].copy()
    if not output.empty:
        # Refresh only derived stage/score fields for the read model. The
        # original observation remains unchanged in the PIT artifact/ledger.
        records = output.to_dict("records")
        for row in records:
            row.setdefault(
                "first_observed_at_utc",
                row.get("retrieved_at_utc"),
            )
        output = pd.DataFrame([enrich_event_row(row, now_utc=now_utc) for row in records])
        output["fallback_status"] = "retained_last_valid_artifact"
    return output


def build_artifact(
    *,
    events: pd.DataFrame,
    history: pd.DataFrame,
    quotes: pd.DataFrame,
    official_components: pd.DataFrame,
    source_health: list[dict[str, Any]],
    generated_at_utc: str,
    trigger_type: str,
    countries: Iterable[str],
    window_start: date,
    window_end: date,
) -> dict[str, Any]:
    quote_latest = quotes.copy()
    if not quote_latest.empty and "symbol" in quote_latest.columns:
        quote_latest["_retrieved"] = pd.to_datetime(
            quote_latest.get("retrieved_at_utc"),
            errors="coerce",
            utc=True,
        )
        quote_latest["_provider_priority"] = quote_latest.get(
            "provider", pd.Series(index=quote_latest.index, dtype=object)
        ).map(
            {
                "futu_opend": 0,
                "finnhub": 1,
            }
        ).fillna(9)
        quote_latest = (
            quote_latest.sort_values(
                ["symbol", "_retrieved", "_provider_priority"],
                ascending=[True, False, True],
            )
            .drop_duplicates("symbol", keep="first")
            .drop(columns=["_retrieved", "_provider_priority"])
            .sort_values("symbol")
        )
    event_rows = _records(events)
    health_by_source = {
        str(row.get("source_id")): str(row.get("status"))
        for row in source_health
    }
    required_ready = (
        health_by_source.get("tradingview_calendar") == "Healthy"
        and health_by_source.get("official_bls") in {"Healthy", "Partial"}
    )
    status = "ready" if event_rows and required_ready else "degraded"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "generated_at_utc": generated_at_utc,
        "trigger_type": trigger_type,
        "window": {
            "from": window_start.isoformat(),
            "to": window_end.isoformat(),
            "countries": sorted({str(value).upper() for value in countries}),
        },
        "events": event_rows,
        "consensus_history": _records(history),
        "quotes": _records(quote_latest),
        "official_components": _records(official_components),
        "component_contracts": list(COMPONENT_CONTRACTS),
        "scenario_templates": {
            family: list(rows) for family, rows in SCENARIO_TEMPLATES.items()
        },
        "source_health": source_health,
        "caveats": [
            "Calendar forecasts are third-party consensus snapshots, not a multi-contributor distribution.",
            "Third-party actuals remain unverified until an official-source collector confirms them.",
            "Consensus dispersion and historical event beta are unavailable in V1 and are not imputed.",
            "Finnhub free quote coverage is US-only in this implementation; Korea/Hong Kong require Futu or another adapter.",
        ],
    }


def run_pipeline(
    *,
    trigger_type: str = "scheduled",
    from_date: date | str | None = None,
    to_date: date | str | None = None,
    countries: Iterable[str] = DEFAULT_COUNTRIES,
    include_quotes: bool = True,
    write: bool = True,
    artifact_path: Path = LATEST_ARTIFACT_PATH,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Run one refresh. A source failure retains the last valid timeline."""
    now = now_utc or datetime.now(timezone.utc)
    start = _date(from_date, now.date() - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    end = _date(to_date, now.date() + timedelta(days=DEFAULT_LOOKAHEAD_DAYS))
    country_values = tuple(sorted({str(value).upper() for value in countries}))
    previous_artifact = load_artifact(artifact_path)
    source_health: list[dict[str, Any]] = []

    try:
        fetched_events, calendar_health = fetch_calendar(
            start,
            end,
            countries=country_values,
            trigger_type=trigger_type,
            now_utc=now,
        )
    except Exception as exc:
        fetched_events = pd.DataFrame()
        calendar_health = {
            "source_id": "tradingview_calendar",
            "status": "Unavailable",
            "retrieved_at_utc": now.isoformat(),
            "records": 0,
            "notes": f"{type(exc).__name__}: calendar refresh failed; last valid artifact retained.",
        }
    source_health.append(calendar_health)

    try:
        component_frame, component_health = fetch_official_components(
            trigger_type=trigger_type,
            now_utc=now,
        )
    except Exception as exc:
        component_frame = pd.DataFrame()
        component_health = {
            "source_id": "official_bls",
            "status": "Unavailable",
            "retrieved_at_utc": now.isoformat(),
            "records": 0,
            "notes": f"{type(exc).__name__}: official BLS component refresh failed.",
        }
    source_health.append(component_health)
    event_ledger_before = load_event_ledger()
    fetched_events = _with_first_observed(
        fetched_events,
        event_ledger=event_ledger_before,
        previous_artifact=previous_artifact,
    )
    if not fetched_events.empty and not component_frame.empty:
        fetched_events = verify_calendar_actuals(fetched_events, component_frame)
    retained_event_count = 0
    if fetched_events.empty:
        current_events = _fallback_events(
            previous_artifact,
            start=start,
            end=end,
            now_utc=now,
        )
        event_ledger = event_ledger_before
    elif write:
        event_ledger = append_event_snapshots(fetched_events)
        current_events = _latest_per_event(fetched_events)
    else:
        event_ledger = fetched_events.copy()
        current_events = _latest_per_event(fetched_events)
    if not fetched_events.empty:
        current_events, retained_event_count = _merge_retained_events(
            current_events,
            previous_artifact,
            start=start,
            end=end,
            now_utc=now,
        )
    if retained_event_count:
        calendar_health["status"] = "Partial"
        calendar_health["notes"] = (
            str(calendar_health.get("notes") or "")
            + f" Retained {retained_event_count} prior-window event(s) absent from this response."
        ).strip()
    if not current_events.empty and not component_frame.empty:
        current_events = verify_calendar_actuals(current_events, component_frame)

    retained_quotes = (
        pd.DataFrame(previous_artifact.get("quotes", []))
        if previous_artifact and previous_artifact.get("quotes")
        else load_quote_ledger()
    )
    if include_quotes:
        key = resolve_credential("FINNHUB_API_KEY", REPO_ROOT)
        quote_frame, quote_health = fetch_quotes(
            MARKET_INSTRUMENTS,
            api_key=key,
            trigger_type=trigger_type,
            now_utc=now,
        )
        futu_frame, futu_health = fetch_futu_quotes(
            trigger_type=trigger_type,
            now_utc=now,
        )
        if not futu_frame.empty:
            quote_frame = pd.DataFrame(
                [*quote_frame.to_dict(orient="records"), *futu_frame.to_dict(orient="records")]
            )
    else:
        quote_frame = pd.DataFrame()
        quote_health = {
            "source_id": "finnhub_quotes",
            "status": "Skipped",
            "retrieved_at_utc": now.isoformat(),
            "records": 0,
            "notes": "Quote refresh disabled for this run.",
        }
        futu_health = {
            "source_id": "futu_opend",
            "status": "Skipped",
            "retrieved_at_utc": now.isoformat(),
            "records": 0,
            "notes": "Quote refresh disabled for this run.",
        }
    source_health.append(quote_health)
    source_health.append(futu_health)

    if include_quotes and write and not quote_frame.empty:
        quote_ledger = append_quote_snapshots(quote_frame)
        if quote_ledger.empty:
            quote_ledger = retained_quotes
        else:
            quote_ledger = _merge_retained_by_key(
                quote_ledger,
                retained_quotes,
                key="symbol",
            )
    elif include_quotes and not quote_frame.empty:
        quote_ledger = _merge_retained_by_key(
            quote_frame,
            retained_quotes,
            key="symbol",
        )
    elif include_quotes:
        quote_ledger = _annotate_retained(retained_quotes)
    elif not include_quotes:
        # --no-quotes is an acquisition switch, not a request to erase the
        # last valid cross-asset snapshot from the compact artifact.
        quote_ledger = retained_quotes
    else:
        quote_ledger = quote_frame

    retained_components = (
        pd.DataFrame(previous_artifact.get("official_components", []))
        if previous_artifact
        else pd.DataFrame()
    )
    if write and not component_frame.empty:
        component_ledger = append_component_snapshots(component_frame)
        component_ledger = _merge_retained_by_key(
            component_ledger,
            retained_components,
            key="series_id",
        )
    elif not component_frame.empty:
        component_ledger = _merge_retained_by_key(
            component_frame,
            retained_components,
            key="series_id",
        )
    else:
        component_base = load_component_ledger()
        component_ledger = _annotate_retained(
            component_base if not component_base.empty else retained_components
        )
    if not component_ledger.empty and "series_id" in component_ledger.columns:
        component_latest = component_ledger.copy()
        component_latest["_retrieved"] = pd.to_datetime(
            component_latest.get("retrieved_at_utc"),
            errors="coerce",
            utc=True,
        )
        component_latest = (
            component_latest.sort_values(["series_id", "_retrieved"])
            .drop_duplicates("series_id", keep="last")
            .drop(columns="_retrieved")
            .sort_values(["event_family", "component_id"])
        )
    else:
        component_latest = component_ledger

    event_ids = (
        set(current_events["event_id"].dropna().astype(str))
        if not current_events.empty and "event_id" in current_events.columns
        else set()
    )
    history = _bounded_history(event_ledger, event_ids)
    artifact = build_artifact(
        events=current_events,
        history=history,
        quotes=quote_ledger,
        official_components=component_latest,
        source_health=source_health,
        generated_at_utc=now.isoformat(),
        trigger_type=trigger_type,
        countries=country_values,
        window_start=start,
        window_end=end,
    )
    if write:
        save_artifact(artifact, path=artifact_path)
        # Return the persisted form, including its semantic content hash.
        artifact = load_artifact(artifact_path) or artifact
    return {
        "artifact": artifact,
        "events": current_events,
        "event_ledger": event_ledger,
        "quotes": quote_frame,
        "official_components": component_latest,
        "source_health": source_health,
        "artifact_path": str(artifact_path),
        "used_previous_artifact": bool(previous_artifact),
    }
