"""Shared freshness semantics for market-monitor observations.

The monitor has three different notions of "latest": a live quote, the last
completed trading session, and the last officially published value.  Keeping
their status calculation here prevents a renderer or an email template from
mistaking retrieval time for observation time.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from .config import FRESHNESS_POLICIES, MARKET_TIMEZONE


UTC = timezone.utc
LOCAL_TZ = ZoneInfo(MARKET_TIMEZONE)
BLOCKING_FRESHNESS_STATUSES = frozenset({"Unavailable", "Stale", "Invalid"})
ALERT_REQUIRED_EXPOSURE_DATASETS = frozenset({"index_close", "etf_close"})
ALERT_NON_BLOCKING_DATASETS = frozenset(
    {"etf_share_daily", "heatmap_etf_price_daily", "southbound_market_flow"}
)


def utc_now() -> datetime:
    """Return an aware UTC timestamp, isolated for deterministic tests."""
    return datetime.now(UTC)


def market_date(now_utc: datetime | None = None) -> str:
    """Return the report date in the configured Asia market timezone."""
    return (now_utc or utc_now()).astimezone(LOCAL_TZ).date().isoformat()


def isoformat_utc(value: datetime | None = None) -> str:
    """Serialize an aware timestamp in the stable ``Z`` representation."""
    current = value or utc_now()
    if current.tzinfo is None:
        raise ValueError("isoformat_utc requires an aware datetime")
    return current.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime | None:
    """Parse ISO-like values without silently treating local time as UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _age_seconds(reference: datetime, now: datetime) -> float:
    return max(0.0, (now - reference).total_seconds())


@lru_cache(maxsize=16)
def _exchange_calendar(name: str):
    """Load a cached exchange calendar; imported lazily for cheap unit tests."""
    from exchange_calendars import get_calendar

    return get_calendar(name)


def last_completed_session_date(
    calendar_name: str,
    *,
    now_utc: datetime | None = None,
) -> date:
    """Return the latest fully closed session for an exchange.

    The report timezone can be many hours ahead of an exchange (notably New
    York), so checking only the local date can accept an in-progress daily bar.
    Walk back until the exchange's official close is no later than ``now_utc``.
    """
    now = (now_utc or utc_now()).astimezone(UTC)
    local_date = now.astimezone(LOCAL_TZ).date().isoformat()
    calendar = _exchange_calendar(calendar_name)
    session = calendar.date_to_session(local_date, direction="previous")
    for _ in range(10):
        close = calendar.session_close(session).to_pydatetime().astimezone(UTC)
        if close <= now:
            return session.date()
        session = calendar.previous_session(session)
    raise ValueError(f"Could not resolve a completed {calendar_name} session near {local_date}")


def expected_latest_session_date(
    calendar_name: str,
    requested_end_date: str | date | None = None,
    *,
    now_utc: datetime | None = None,
) -> date:
    """Resolve the latest completed session inside a requested date window.

    Historical/backfill requests may end before today, while an EOD source can
    also return an in-progress current-day bar before the exchange closes. The
    expected observation is therefore the earlier of the requested window's
    last session and the exchange's latest fully completed session.
    """
    completed = last_completed_session_date(calendar_name, now_utc=now_utc)
    if requested_end_date is None:
        return completed

    if isinstance(requested_end_date, datetime):
        requested = requested_end_date.date()
    elif isinstance(requested_end_date, date):
        requested = requested_end_date
    else:
        text = str(requested_end_date).strip().replace("-", "")
        if len(text) < 8 or not text[:8].isdigit():
            raise ValueError(f"Invalid requested end date: {requested_end_date!r}")
        requested = date(int(text[:4]), int(text[4:6]), int(text[6:8]))

    calendar = _exchange_calendar(calendar_name)
    requested_session = calendar.date_to_session(
        requested.isoformat(), direction="previous"
    ).date()
    return min(completed, requested_session)


def alert_fetch_error_is_required(error: Any) -> bool:
    """Whether a fetch error affects data shown in the compact ETF email.

    Index/ETF histories for non-core exposures remain visible in dashboard
    health but do not suppress the three-exposure email. Unknown required
    datasets fail closed; explicitly optional and event notices do not become
    data blockers.
    """
    if not isinstance(error, Mapping):
        return True
    if error.get("severity") in {"optional", "event"}:
        return False
    dataset = str(error.get("dataset") or "")
    if dataset in ALERT_REQUIRED_EXPOSURE_DATASETS:
        from .config import ALERT_CORE_EXPOSURES

        exposure_id = str(error.get("exposure_id") or "")
        # Missing ownership metadata is not proof that the failed fetch was
        # irrelevant; only a positively identified non-core exposure is safe
        # to ignore for this compact report.
        return not exposure_id or exposure_id in ALERT_CORE_EXPOSURES
    if dataset == "etf_spot":
        # Quote freshness/availability is checked separately. A name-vs-
        # registry contradiction is different: it can put a fund in the wrong
        # peer cohort and must still fail closed.
        return str(error.get("error") or "").startswith("RegistryMismatch")
    if dataset in ALERT_NON_BLOCKING_DATASETS:
        return False
    return True


def alert_fetch_error_is_relevant(error: Any) -> bool:
    """Whether a fetch error belongs in the compact email's warning count."""
    if not isinstance(error, Mapping):
        return True
    if error.get("severity") in {"optional", "event"}:
        return False
    dataset = str(error.get("dataset") or "")
    if dataset in ALERT_REQUIRED_EXPOSURE_DATASETS:
        from .config import ALERT_CORE_EXPOSURES

        exposure_id = str(error.get("exposure_id") or "")
        return not exposure_id or exposure_id in ALERT_CORE_EXPOSURES
    return dataset not in {"etf_share_daily", "heatmap_etf_price_daily"}


def classify_intraday_quote(
    *,
    retrieved_at_utc: Any,
    source_observed_at_utc: Any = None,
    now_utc: datetime | None = None,
    quote_available: bool | None = None,
) -> dict[str, Any]:
    """Classify a quote using source time when available, retrieval time otherwise.

    A retrieval timestamp is never presented as an exchange observation time.
    When the source has no observation timestamp, a recently retrieved quote is
    ``Unverified`` rather than ``Fresh``. It can be shown as a recent snapshot,
    but it must not enter current-signal ranking. ``quote_available`` is
    explicit so an empty response cannot be mistaken for a successful fetch at
    the caller's request time.
    """
    now = (now_utc or utc_now()).astimezone(UTC)
    source_time = parse_timestamp(source_observed_at_utc)
    retrieved_time = parse_timestamp(retrieved_at_utc)
    if quote_available is False:
        return {
            "status": "Unavailable",
            "observed_at_utc": None,
            "retrieved_at_utc": retrieved_time and isoformat_utc(retrieved_time),
            "age_seconds": None,
            "timestamp_basis": "missing",
            "source_time_verified": False,
            "observation_type": "intraday_quote",
        }
    reference = source_time or retrieved_time
    if reference is None:
        return {
            "status": "Unavailable",
            "observed_at_utc": None,
            "retrieved_at_utc": retrieved_time and isoformat_utc(retrieved_time),
            "age_seconds": None,
            "timestamp_basis": "missing",
            "source_time_verified": False,
            "observation_type": "intraday_quote",
        }

    age = _age_seconds(reference, now)
    limit = timedelta(minutes=FRESHNESS_POLICIES["intraday_quote"]["max_age_minutes"])
    if age > limit.total_seconds():
        status = "Stale"
    elif source_time is not None:
        status = "Fresh"
    else:
        status = "Unverified"
    return {
        "status": status,
        "observed_at_utc": source_time and isoformat_utc(source_time),
        "retrieved_at_utc": retrieved_time and isoformat_utc(retrieved_time),
        "age_seconds": round(age, 3),
        "timestamp_basis": "source_observed_at" if source_time else "retrieved_at",
        "source_time_verified": source_time is not None,
        "observation_type": "intraday_quote",
    }


def classify_daily_groups(
    latest_by_exposure: Mapping[str, Any],
    exposure_specs: Iterable[Mapping[str, Any]],
    *,
    group_key: str,
    now_utc: datetime | None = None,
    observation_type: str = "daily_close",
) -> dict[str, dict[str, Any]]:
    """Classify daily coverage independently for each configured group.

    Each member is checked against its own exchange calendar when configured.
    The group's freshness is the worst member status; this avoids comparing
    dates from different time zones as if they were sessions on one market.
    """
    groups: dict[str, list[str]] = {}
    specs = list(exposure_specs)
    spec_by_id: dict[str, Mapping[str, Any]] = {}
    for spec in specs:
        exposure_id = str(spec.get("exposure_id") or "")
        group = str(spec.get(group_key) or "Unknown")
        if exposure_id:
            groups.setdefault(group, []).append(exposure_id)
            spec_by_id[exposure_id] = spec

    classified: dict[str, dict[str, Any]] = {}
    for group, exposure_ids in groups.items():
        observed: dict[str, str] = {}
        invalid_exposures: list[str] = []
        stale_exposures: list[str] = []
        member_records: dict[str, dict[str, Any]] = {}
        for exposure_id in exposure_ids:
            record = classify_daily_observation(
                latest_by_exposure.get(exposure_id),
                now_utc=now_utc,
                observation_type=observation_type,
                session_calendar=spec_by_id[exposure_id].get("session_calendar"),
            )
            member_records[exposure_id] = record
            if record.get("observation_date"):
                observed[exposure_id] = str(record["observation_date"])
            if record.get("status") == "Invalid":
                invalid_exposures.append(exposure_id)
            if record.get("status") == "Stale":
                stale_exposures.append(exposure_id)

        missing = sorted(set(exposure_ids) - set(observed))
        statuses = {str(item.get("status")) for item in member_records.values()}
        if invalid_exposures:
            status = "Invalid"
        elif missing:
            status = "Unavailable"
        elif stale_exposures:
            status = "Stale"
        elif statuses == {"Current session"}:
            status = "Current session"
        else:
            status = "Last session"
        ages = [
            int(item["age_calendar_days"])
            for item in member_records.values()
            if item.get("age_calendar_days") is not None
        ]
        record: dict[str, Any] = {
            "status": status,
            "observation_date": min(observed.values()) if observed else None,
            "age_calendar_days": max(ages) if ages else None,
            "observation_type": observation_type,
            "status_by_exposure": {
                exposure_id: item.get("status")
                for exposure_id, item in member_records.items()
            },
            "expected_session_by_exposure": {
                exposure_id: item.get("expected_session_date")
                for exposure_id, item in member_records.items()
                if item.get("expected_session_date")
            },
        }
        record.update(
            {
                "group": group,
                "expected_count": len(exposure_ids),
                "observed_count": len(observed),
                "missing_exposures": missing,
                "invalid_exposures": sorted(invalid_exposures),
                "stale_exposures": sorted(stale_exposures),
                "latest_by_exposure": observed,
            }
        )
        classified[group] = record
    return classified


def classify_daily_exposures(
    latest_by_exposure: Mapping[str, Any],
    exposure_specs: Iterable[Mapping[str, Any]],
    *,
    now_utc: datetime | None = None,
    observation_type: str = "daily_close",
) -> dict[str, dict[str, Any]]:
    """Classify each configured exposure against its own market calendar."""
    return {
        str(spec["exposure_id"]): classify_daily_observation(
            latest_by_exposure.get(str(spec["exposure_id"])),
            now_utc=now_utc,
            observation_type=observation_type,
            session_calendar=spec.get("session_calendar"),
        )
        for spec in exposure_specs
        if spec.get("exposure_id")
    }


def classify_daily_observation(
    observation_date: Any,
    *,
    now_utc: datetime | None = None,
    observation_type: str = "daily_close",
    session_calendar: str | None = None,
) -> dict[str, Any]:
    """Classify a daily/session observation without calling it today's close.

    When an exchange calendar is configured, freshness is measured against
    that exchange's last completed session. Other datasets use a conservative
    calendar-day bound because their publication cadence has no trading
    calendar.
    """
    now = (now_utc or utc_now()).astimezone(UTC)
    now_local = now.astimezone(LOCAL_TZ)
    try:
        if isinstance(observation_date, datetime):
            parsed_date = observation_date.date()
        elif isinstance(observation_date, date):
            parsed_date = observation_date
        else:
            parsed_date = date.fromisoformat(str(observation_date)[:10])
    except (TypeError, ValueError):
        return {
            "status": "Unavailable",
            "observation_date": None,
            "age_calendar_days": None,
            "observation_type": observation_type,
        }

    age_days = (now_local.date() - parsed_date).days
    expected_session_date = None
    if session_calendar:
        try:
            expected_session_date = last_completed_session_date(
                session_calendar,
                now_utc=now,
            ).isoformat()
        except Exception as exc:  # noqa: BLE001 - calendar failure must fail closed
            return {
                "status": "Unavailable",
                "observation_date": parsed_date.isoformat(),
                "age_calendar_days": age_days,
                "observation_type": observation_type,
                "session_calendar": session_calendar,
                "calendar_error": f"{type(exc).__name__}: {exc}",
            }
        expected = date.fromisoformat(expected_session_date)
        if parsed_date > expected:
            status = "Invalid"
        elif parsed_date < expected:
            status = "Stale"
        else:
            status = "Current session" if parsed_date == now_local.date() else "Last session"
    elif age_days < 0:
        status = "Invalid"
    elif age_days > FRESHNESS_POLICIES[observation_type]["stale_after_calendar_days"]:
        status = "Stale"
    elif age_days == 0:
        status = "Current session"
    else:
        status = "Last session"
    record: dict[str, Any] = {
        "status": status,
        "observation_date": parsed_date.isoformat(),
        "age_calendar_days": age_days,
        "observation_type": observation_type,
    }
    if session_calendar:
        record["session_calendar"] = session_calendar
        record["expected_session_date"] = expected_session_date
    return record


STATUS_LABELS_ZH = {
    "Fresh": "已更新",
    "Unverified": "已抓取（未验证源端时间）",
    "Current session": "当日交易时段",
    "Last session": "最近交易日",
    "Stale": "已过期",
    "Unavailable": "不可用",
    "Invalid": "无效",
}


def display_status(status: Any, *, language: str = "en") -> str:
    """Return a user-facing status without changing the data contract."""
    value = str(status or "Unavailable")
    if language.lower().startswith("zh"):
        return STATUS_LABELS_ZH.get(value, value)
    return value


def freshness_note(record: dict[str, Any], *, language: str = "en") -> str:
    """Compact human-readable note for email/dashboard captions."""
    status = display_status(record.get("status"), language=language)
    if record.get("status") in {"Fresh", "Unverified"} and record.get("timestamp_basis") == "retrieved_at":
        status = (
            "已抓取（源端时间未提供）"
            if language.lower().startswith("zh")
            else "Recently retrieved (source time unavailable)"
        )
    if record.get("observation_date"):
        return f"{status} · {record['observation_date']}"
    if record.get("observed_at_utc"):
        return f"{status} · {record['observed_at_utc']}"
    if record.get("retrieved_at_utc"):
        prefix = "抓取" if language.lower().startswith("zh") else "retrieved"
        return f"{status} · {prefix} {record['retrieved_at_utc']}"
    return status
