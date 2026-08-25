"""Shared freshness semantics for market-monitor observations.

The monitor has three different notions of "latest": a live quote, the last
completed trading session, and the last officially published value.  Keeping
their status calculation here prevents a renderer or an email template from
mistaking retrieval time for observation time.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import FRESHNESS_POLICIES, MARKET_TIMEZONE


UTC = timezone.utc
LOCAL_TZ = ZoneInfo(MARKET_TIMEZONE)
BLOCKING_FRESHNESS_STATUSES = frozenset({"Unavailable", "Stale", "Invalid"})


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

    The aggregate latest date is useful as a headline, but its maximum can
    hide a stalled market. This helper uses the oldest observed latest date in
    each group and marks a group unavailable when any configured exposure is
    missing. The per-exposure dates remain in the record for auditability.
    """
    groups: dict[str, list[str]] = {}
    for spec in exposure_specs:
        exposure_id = str(spec.get("exposure_id") or "")
        group = str(spec.get(group_key) or "Unknown")
        if exposure_id:
            groups.setdefault(group, []).append(exposure_id)

    classified: dict[str, dict[str, Any]] = {}
    for group, exposure_ids in groups.items():
        observed: dict[str, str] = {}
        invalid_exposures: list[str] = []
        for exposure_id in exposure_ids:
            record = classify_daily_observation(
                latest_by_exposure.get(exposure_id),
                now_utc=now_utc,
                observation_type=observation_type,
            )
            if record.get("observation_date"):
                observed[exposure_id] = str(record["observation_date"])
            if record.get("status") == "Invalid":
                invalid_exposures.append(exposure_id)

        missing = sorted(set(exposure_ids) - set(observed))
        if observed:
            # Conservative group date: a group is not current while one of its
            # members is still on an older session.
            record = classify_daily_observation(
                min(observed.values()),
                now_utc=now_utc,
                observation_type=observation_type,
            )
        else:
            record = classify_daily_observation(
                None,
                now_utc=now_utc,
                observation_type=observation_type,
            )
        if invalid_exposures:
            # A future-dated member must not disappear behind the minimum of
            # the other dates. Preserve the conservative group date for
            # context, but make the invalid member authoritative for status.
            record["status"] = "Invalid"
        elif missing:
            record["status"] = "Unavailable"
        record.update(
            {
                "group": group,
                "expected_count": len(exposure_ids),
                "observed_count": len(observed),
                "missing_exposures": missing,
                "invalid_exposures": sorted(invalid_exposures),
                "latest_by_exposure": observed,
            }
        )
        classified[group] = record
    return classified


def classify_daily_observation(
    observation_date: Any,
    *,
    now_utc: datetime | None = None,
    observation_type: str = "daily_close",
) -> dict[str, Any]:
    """Classify a daily/session observation without calling it today's close.

    The monitor does not maintain a hard-coded holiday table.  A dated daily
    row before the local calendar date is therefore reported as ``Last
    session`` until the configurable safety bound is exceeded.  This is honest
    on weekends and holidays while still detecting a provider that has stopped
    moving altogether.
    """
    now_local = (now_utc or utc_now()).astimezone(LOCAL_TZ)
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
    if age_days < 0:
        status = "Invalid"
    elif age_days > FRESHNESS_POLICIES[observation_type]["stale_after_calendar_days"]:
        status = "Stale"
    elif age_days == 0:
        status = "Current session"
    else:
        status = "Last session"
    return {
        "status": status,
        "observation_date": parsed_date.isoformat(),
        "age_calendar_days": age_days,
        "observation_type": observation_type,
    }


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
