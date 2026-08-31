"""Event-driven delivery policy for the market-monitor Gmail report.

The report contains a useful amount of context, but it should not arrive just
because a scheduled job happened to run.  This module separates that delivery
decision from the email renderer:

* market events are detected from the same historical datasets used by the
  dashboard;
* a new state must persist for the configured number of observations before it
  is considered an alert;
* a tiny JSON cursor prevents close/intraday retries from replaying history;
* Friday provides a weekly no-change heartbeat so a quiet market does not
  become a silent system failure.

No price history is copied into the state file.  The state contains only
observation cursors, delivery metadata and (when Gmail fails) a small pending
event queue for retry.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import (
    ALERT_CORE_EXPOSURES,
    ALERT_CONFIRMATION_OBSERVATIONS,
    ALERT_DRAWDOWN_TRIGGER_PCT,
    ALERT_HEARTBEAT_WEEKDAY,
    ALERT_MAX_EVENTS_IN_EMAIL,
    ALERT_MA20_BAND_PCT,
    ALERT_PREMIUM_LEADER_MIN_GAP_PCT,
    ALERT_RELATIVE_ZSCORE_TRIGGER,
    ALERT_RSI_OVERBOUGHT,
    ALERT_RSI_OVERSOLD,
    ALERT_STATE_MAX_EVENT_KEYS,
    ALERT_STATE_PATH,
    ALERT_STATE_VERSION,
    EXPOSURES,
)
from .freshness import BLOCKING_FRESHNESS_STATUSES
from .ranking import classify_entry_status
from .relative_strength import RELATIVE_PAIRS
from .technicals import compute_technical_history


_EXTREME_ENTRY_STATUSES = frozenset({"ATTRACTIVE", "AVOID"})
_STATUS_LABELS_ZH = {
    "ATTRACTIVE": "同类溢价偏低",
    "FAIR": "合理区间",
    "EXPENSIVE": "溢价偏高",
    "AVOID": "溢价过高",
}
_ZONE_LABELS_ZH = {
    "above": "站上均线",
    "below": "跌破均线",
    "neutral": "均线附近",
    "oversold": "超卖",
    "overbought": "超买",
    "drawdown": "进入较深回撤",
    "normal": "正常回撤区间",
    "numerator": "偏向分子",
    "denominator": "偏向分母",
}
_EVENT_PRIORITY = {
    "fee_change": 0,
    "fee_registry_mismatch": 7,
    "drawdown": 1,
    "trend_reversal": 2,
    "entry_status": 3,
    "relative_extreme": 4,
    "rsi_extreme": 5,
    "leader_change": 6,
    "data_event": 7,
    "weekly_heartbeat": 8,
}


_EVENT_PREFIXES_ZH = {
    "fee_change": "费率变化",
    "fee_registry_mismatch": "登记费率与发行方不一致",
    "data_event": "重要数据事件",
}


@dataclass(frozen=True)
class AlertEvent:
    """One material change that can explain why an email was sent."""

    event_type: str
    entity_id: str
    label: str
    observation_date: str
    detail: str
    priority: int = 99
    # A market event is a dated observation, so its date belongs in the key.
    # An operational event describes a *condition* seen at run time: a registry
    # row that disagrees with the issuer stays wrong every day until a human
    # edits it, and dating its key would mail the same sentence every morning
    # forever. Keying it on the message instead means it alerts once and again
    # only when the message itself changes.
    recurring_condition: bool = False

    @property
    def event_key(self) -> str:
        parts = [self.event_type, self.entity_id]
        if not self.recurring_condition:
            parts.append(self.observation_date)
        parts.append(self.detail)
        return "|".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "entity_id": self.entity_id,
            "label": self.label,
            "observation_date": self.observation_date,
            "detail": self.detail,
            "priority": self.priority,
            "recurring_condition": self.recurring_condition,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AlertEvent | None":
        required = ("event_type", "entity_id", "label", "observation_date", "detail")
        if not all(str(value.get(key) or "").strip() for key in required):
            return None
        return cls(
            event_type=str(value["event_type"]),
            entity_id=str(value["entity_id"]),
            label=str(value["label"]),
            observation_date=str(value["observation_date"]),
            detail=str(value["detail"]),
            priority=int(value.get("priority", _EVENT_PRIORITY.get(str(value["event_type"]), 99))),
            # A queued event must keep its identity across the retry, or the
            # retry would be keyed differently from the send that failed.
            recurring_condition=bool(value.get("recurring_condition", False)),
        )


@dataclass(frozen=True)
class AlertDecision:
    """Delivery decision returned to the CLI."""

    should_send: bool
    kind: str
    report_date: str
    observation_date: str | None
    events: tuple[AlertEvent, ...] = ()
    reason_lines: tuple[str, ...] = ()
    total_event_count: int = 0

    @property
    def subject_prefix(self) -> str:
        return {
            "baseline": "Index & ETF Monitor Baseline",
            "event": "Index & ETF Alert",
            "weekly": "Index & ETF Weekly Digest",
            "manual": "Index & ETF Monitor Manual Report",
        }.get(self.kind, "Index & ETF Monitor")


def _default_state() -> dict[str, Any]:
    return {
        "version": ALERT_STATE_VERSION,
        "baseline_initialized": False,
        "last_evaluated_by_mode": {"close": None, "intraday": None},
        "last_sent_report_date": None,
        "last_sent_week": None,
        "last_sent_kind": None,
        "pending_events": [],
        "sent_event_keys": [],
    }


def _normalise_state(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or raw.get("version") != ALERT_STATE_VERSION:
        return _default_state()
    state = _default_state()
    state["baseline_initialized"] = bool(raw.get("baseline_initialized"))
    cursors = raw.get("last_evaluated_by_mode")
    if isinstance(cursors, Mapping):
        for mode in ("close", "intraday"):
            value = cursors.get(mode)
            state["last_evaluated_by_mode"][mode] = str(value) if value else None
    for key in ("last_sent_report_date", "last_sent_week", "last_sent_kind"):
        value = raw.get(key)
        state[key] = str(value) if value else None
    pending: list[dict[str, Any]] = []
    for item in raw.get("pending_events", []) if isinstance(raw.get("pending_events", []), list) else []:
        event = AlertEvent.from_mapping(item) if isinstance(item, Mapping) else None
        if event is not None:
            pending.append(event.as_dict())
    state["pending_events"] = pending[-ALERT_STATE_MAX_EVENT_KEYS:]
    sent_keys = raw.get("sent_event_keys")
    if isinstance(sent_keys, list):
        state["sent_event_keys"] = [
            str(key)
            for key in sent_keys
            if str(key or "").strip()
        ][-ALERT_STATE_MAX_EVENT_KEYS:]
    return state


def load_alert_state(path: Path | str | None = None) -> dict[str, Any]:
    """Load the tiny delivery cursor; a missing/corrupt file starts a baseline."""
    state_path = Path(path) if path is not None else ALERT_STATE_PATH
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _default_state()
    return _normalise_state(raw)


def save_alert_state(state: Mapping[str, Any], path: Path | str | None = None) -> None:
    """Atomically persist delivery metadata without storing market history."""
    state_path = Path(path) if path is not None else ALERT_STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_normalise_state(state), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary_path = state_path.with_name(f".{state_path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8")
    temporary_path.replace(state_path)


def _date_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).date().isoformat()


def _normalise_date_column(frame: pd.DataFrame, column: str = "date") -> pd.DataFrame:
    if frame is None or frame.empty or column not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out[column] = pd.to_datetime(out[column], errors="coerce").dt.strftime("%Y-%m-%d")
    return out[out[column].notna()].copy()


def _normalise_ticker(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).split(".", 1)[0].strip()
    if not text:
        return None
    return text.zfill(6) if text.isdigit() else text


def _exposure_labels() -> dict[str, str]:
    return {
        str(spec["exposure_id"]): str(spec.get("label_zh") or spec["exposure_id"])
        for spec in EXPOSURES
    }


def _latest_observation_date(*frames: pd.DataFrame) -> str | None:
    dates: list[str] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for column in ("date", "trade_date"):
            if column not in frame.columns:
                continue
            values = pd.to_datetime(frame[column], errors="coerce").dropna()
            if not values.empty:
                dates.append(values.max().date().isoformat())
    return max(dates) if dates else None


def _wrapper_maps(wrappers: pd.DataFrame) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return ticker -> exposure, fund name and premium regime maps."""
    exposure_by_ticker: dict[str, str] = {}
    name_by_ticker: dict[str, str] = {}
    regime_by_ticker: dict[str, str] = {}
    if wrappers is None or wrappers.empty:
        return exposure_by_ticker, name_by_ticker, regime_by_ticker
    for row in wrappers.to_dict("records"):
        ticker = _normalise_ticker(row.get("ticker") or row.get("fund_id"))
        exposure_id = str(row.get("exposure_id") or "").strip()
        if not ticker or not exposure_id:
            continue
        exposure_by_ticker[ticker] = exposure_id
        name_by_ticker[ticker] = str(row.get("fund_name") or ticker)
        regime = row.get("premium_regime")
        if regime is None or pd.isna(regime):
            regime = "quota" if bool(row.get("is_cross_border", False)) else "domestic"
        regime_by_ticker[ticker] = str(regime)
    return exposure_by_ticker, name_by_ticker, regime_by_ticker


def _premium_history_with_current(
    premium_history: pd.DataFrame,
    wrappers: pd.DataFrame,
    *,
    report_date: str,
) -> pd.DataFrame:
    """Prepare historical premium rows and append only verified current quotes."""
    history = _normalise_date_column(premium_history)
    exposure_by_ticker, _, _ = _wrapper_maps(wrappers)
    if history.empty:
        history = pd.DataFrame(columns=["date", "ticker", "premium_pct", "exposure_id"])
    if "ticker" not in history.columns and "fund_id" in history.columns:
        history["ticker"] = history["fund_id"]
    if "ticker" not in history.columns:
        history["ticker"] = pd.Series(dtype=str)
    history["ticker"] = history["ticker"].map(_normalise_ticker)
    if "exposure_id" not in history.columns:
        history["exposure_id"] = history["ticker"].map(exposure_by_ticker)
    else:
        history["exposure_id"] = history["exposure_id"].fillna(history["ticker"].map(exposure_by_ticker))
    if "premium_pct" not in history.columns:
        history["premium_pct"] = np.nan
    history["premium_pct"] = pd.to_numeric(history["premium_pct"], errors="coerce")
    # Keep unverified IOPV observations for audit/chart consumers, but never
    # let them create a current alert.  Older artifacts without ``basis`` stay
    # compatible; the pipeline labels all newly written rows explicitly.
    if "basis" in history.columns:
        trusted_basis = history["basis"].isna() | history["basis"].astype(str).isin(
            {"nav", "iopv", "verified_current_quote"}
        )
        history = history.loc[trusted_basis].copy()

    if wrappers is not None and not wrappers.empty and {"ticker", "premium_pct", "exposure_id"}.issubset(wrappers.columns):
        current = wrappers.copy()
        current["ticker"] = current["ticker"].map(_normalise_ticker)
        current["premium_pct"] = pd.to_numeric(current["premium_pct"], errors="coerce")
        usable = current["ticker"].notna() & current["premium_pct"].notna()
        if "quote_status" in current.columns:
            usable &= current["quote_status"].fillna("").astype(str).eq("Fresh")
        if "quote_basis" in current.columns:
            usable &= ~current["quote_basis"].fillna("").astype(str).eq("last_close")
        current = current.loc[usable, ["ticker", "premium_pct", "exposure_id"]].copy()
        if not current.empty:
            current["date"] = report_date
            current["basis"] = "verified_current_quote"
            history = pd.concat([history, current], ignore_index=True, sort=False)

    history = history.dropna(subset=["date", "ticker", "premium_pct"])
    return history.drop_duplicates(["date", "ticker"], keep="last").sort_values(["ticker", "date"])


def _confirmed_transitions(
    states: pd.Series,
    values: pd.Series | None,
    *,
    after_date: str | None,
    transition_filter: Callable[[str, str], bool],
) -> list[tuple[str, str, str, object]]:
    """Return transitions that persist for the configured observations."""
    if states is None or states.empty:
        return []
    frame = pd.DataFrame({"state": states.astype("object")})
    if values is not None:
        frame["value"] = values.reindex(frame.index)
    else:
        frame["value"] = np.nan
    frame.index = [_date_text(index) for index in frame.index]
    frame = frame.loc[[index is not None for index in frame.index]]
    if frame.empty:
        return []
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    confirmation_count = max(1, int(ALERT_CONFIRMATION_OBSERVATIONS))
    events: list[tuple[str, str, str, object]] = []

    def _missing(value: object) -> bool:
        if value is None:
            return True
        try:
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False

    for position in range(1, len(frame)):
        old_value = frame.iloc[position - 1]["state"]
        new_value = frame.iloc[position]["state"]
        # A missing/invalid observation is a hard break.  Dropping it would
        # turn ``above, missing, below, below`` into a false consecutive move.
        if _missing(old_value) or _missing(new_value):
            continue
        old_state = str(old_value)
        new_state = str(new_value)
        if old_state == new_state or not transition_filter(old_state, new_state):
            continue
        end = position + confirmation_count - 1
        if end >= len(frame):
            continue
        confirmed_values = frame.iloc[position:end + 1]["state"].tolist()
        if any(_missing(value) or str(value) != new_state for value in confirmed_values):
            continue
        event_date = str(frame.index[end])
        if after_date is not None and event_date <= after_date:
            continue
        events.append((event_date, old_state, new_state, frame.iloc[end]["value"]))
    return events


def _event(
    event_type: str,
    entity_id: str,
    label: str,
    observation_date: str,
    detail: str,
    *,
    recurring_condition: bool = False,
) -> AlertEvent:
    return AlertEvent(
        event_type=event_type,
        entity_id=entity_id,
        label=label,
        observation_date=observation_date,
        detail=detail,
        priority=_EVENT_PRIORITY.get(event_type, 99),
        recurring_condition=recurring_condition,
    )


def _detect_entry_status_events(
    premium_history: pd.DataFrame,
    wrappers: pd.DataFrame,
    *,
    after_date: str | None,
) -> list[AlertEvent]:
    # ``evaluate_alert`` has already appended the verified current quote. Do
    # not append it a second time with the cursor date: that would move a
    # current-day observation backwards when the run is replayed.
    history = _normalise_date_column(premium_history)
    if history.empty or not {"ticker", "date", "premium_pct", "exposure_id"}.issubset(history.columns):
        return []
    exposure_by_ticker, names, regimes = _wrapper_maps(wrappers)
    labels = _exposure_labels()
    events: list[AlertEvent] = []
    for ticker, group in history.groupby("ticker", sort=False):
        group = group.sort_values("date").drop_duplicates("date", keep="last")
        exposure_id = str(group["exposure_id"].dropna().iloc[-1]) if group["exposure_id"].notna().any() else exposure_by_ticker.get(str(ticker), "")
        if exposure_id not in ALERT_CORE_EXPOSURES:
            continue
        regime = regimes.get(str(ticker), "domestic")
        statuses = group["premium_pct"].map(lambda value: classify_entry_status(value, regime))
        statuses = statuses.mask(statuses.eq("UNAVAILABLE"))
        statuses.index = group["date"].tolist()
        values = pd.Series(group["premium_pct"].to_numpy(), index=statuses.index)
        transitions = _confirmed_transitions(
            statuses,
            values,
            after_date=after_date,
            transition_filter=lambda old, new: new in _EXTREME_ENTRY_STATUSES,
        )
        fund_name = names.get(str(ticker), str(ticker))
        display = f"{labels.get(exposure_id, exposure_id)} · {fund_name}"
        for event_date, old_state, new_state, premium in transitions:
            old_label = _STATUS_LABELS_ZH.get(old_state, old_state)
            new_label = _STATUS_LABELS_ZH.get(new_state, new_state)
            premium_text = "—" if pd.isna(premium) else f"{float(premium):+.2f}%"
            events.append(
                _event(
                    "entry_status",
                    f"{exposure_id}:{ticker}",
                    display,
                    event_date,
                    f"{display}：{old_label} → {new_label}，溢价率 {premium_text}。",
                )
            )
    return events


def _detect_leader_events(
    premium_history: pd.DataFrame,
    wrappers: pd.DataFrame,
    *,
    after_date: str | None,
) -> list[AlertEvent]:
    history = _normalise_date_column(premium_history)
    required = {"date", "ticker", "premium_pct", "exposure_id"}
    if history.empty or not required.issubset(history.columns):
        return []
    _, names, _ = _wrapper_maps(wrappers)
    labels = _exposure_labels()
    events: list[AlertEvent] = []
    for exposure_id, group in history.groupby("exposure_id", sort=False):
        if str(exposure_id) not in ALERT_CORE_EXPOSURES:
            continue
        pivot = group.pivot_table(index="date", columns="ticker", values="premium_pct", aggfunc="last")
        leaders: dict[str, str | None] = {}
        gaps: dict[str, float] = {}
        for observation_date, row in pivot.iterrows():
            ordered = row.dropna().sort_values()
            if len(ordered) < 2:
                leaders[str(observation_date)] = None
                continue
            gap = float(ordered.iloc[1] - ordered.iloc[0])
            # A raw lowest-premium ticker is not a meaningful leader while the
            # cohort is effectively tied.  Retaining an explicit unqualified
            # state lets a later widening gap generate an alert.
            leaders[str(observation_date)] = (
                str(ordered.index[0])
                if gap >= ALERT_PREMIUM_LEADER_MIN_GAP_PCT
                else "unqualified"
            )
            gaps[str(observation_date)] = gap
        if not leaders:
            continue
        states = pd.Series(leaders, dtype="object")
        values = pd.Series(gaps, dtype=float)
        transitions = _confirmed_transitions(
            states,
            values,
            after_date=after_date,
            transition_filter=lambda old, new: new not in {"unqualified", "None"} and old != new,
        )
        for event_date, old_ticker, new_ticker, gap in transitions:
            new_name = names.get(new_ticker, new_ticker)
            old_name = (
                "同类尚未拉开差距"
                if old_ticker == "unqualified"
                else names.get(old_ticker, old_ticker)
            )
            label = labels.get(str(exposure_id), str(exposure_id))
            events.append(
                _event(
                    "leader_change",
                    f"{exposure_id}:{new_ticker}",
                    label,
                    event_date,
                    f"{label}：同类最低溢价由 {old_ticker} {old_name} 换为 {new_ticker} {new_name}，领先 {float(gap):+.2f} 个百分点。",
                )
            )
    return events


def _technical_state(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if number >= ALERT_MA20_BAND_PCT:
        return "above"
    if number <= -ALERT_MA20_BAND_PCT:
        return "below"
    return "neutral"


def _rsi_state(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if number >= ALERT_RSI_OVERBOUGHT:
        return "overbought"
    if number <= ALERT_RSI_OVERSOLD:
        return "oversold"
    return "neutral"


def _drawdown_state(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return "drawdown" if float(value) <= ALERT_DRAWDOWN_TRIGGER_PCT else "normal"


def _detect_technical_events(index_prices: pd.DataFrame, *, after_date: str | None) -> list[AlertEvent]:
    prices = _normalise_date_column(index_prices)
    required = {"date", "exposure_id", "close"}
    if prices.empty or not required.issubset(prices.columns):
        return []
    labels = _exposure_labels()
    events: list[AlertEvent] = []
    for exposure_id, group in prices.groupby("exposure_id", sort=False):
        exposure_id = str(exposure_id)
        if exposure_id not in ALERT_CORE_EXPOSURES:
            continue
        group = group.sort_values("date").drop_duplicates("date", keep="last")
        close = pd.to_numeric(group["close"], errors="coerce")
        close.index = group["date"].tolist()
        technicals = compute_technical_history(close)
        if technicals.empty:
            continue
        label = labels.get(exposure_id, exposure_id)

        trend_states = technicals["ma20_pct"].map(_technical_state)
        trend_states.index = technicals.index
        trend_values = technicals["ma20_pct"]
        for event_date, old_state, new_state, value in _confirmed_transitions(
            trend_states,
            trend_values,
            after_date=after_date,
            transition_filter=lambda old, new: new in {"above", "below"} and old != new,
        ):
            value_text = "—" if pd.isna(value) else f"{float(value):+.2f}%"
            events.append(
                _event(
                    "trend_reversal",
                    exposure_id,
                    label,
                    event_date,
                    f"{label}：20日均线由 {_ZONE_LABELS_ZH.get(old_state, old_state)} 转为 {_ZONE_LABELS_ZH.get(new_state, new_state)}，相对均线 {value_text}。",
                )
            )

        rsi_states = technicals["rsi"].map(_rsi_state)
        rsi_states.index = technicals.index
        for event_date, old_state, new_state, value in _confirmed_transitions(
            rsi_states,
            technicals["rsi"],
            after_date=after_date,
            transition_filter=lambda old, new: new in {"oversold", "overbought"},
        ):
            value_text = "—" if pd.isna(value) else f"{float(value):.0f}"
            events.append(
                _event(
                    "rsi_extreme",
                    exposure_id,
                    label,
                    event_date,
                    f"{label}：RSI 由 {_ZONE_LABELS_ZH.get(old_state, old_state)} 进入 {_ZONE_LABELS_ZH.get(new_state, new_state)}（RSI {value_text}）。",
                )
            )

        drawdown_states = technicals["drawdown_60d"].map(_drawdown_state)
        drawdown_states.index = technicals.index
        for event_date, old_state, new_state, value in _confirmed_transitions(
            drawdown_states,
            technicals["drawdown_60d"],
            after_date=after_date,
            transition_filter=lambda old, new: new == "drawdown",
        ):
            value_text = "—" if pd.isna(value) else f"{float(value):+.2f}%"
            events.append(
                _event(
                    "drawdown",
                    exposure_id,
                    label,
                    event_date,
                    f"{label}：60日回撤进入风险区间（当前 {value_text}）。",
                )
            )
    return events


def _pair_zone(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if number > ALERT_RELATIVE_ZSCORE_TRIGGER:
        return "numerator"
    if number < -ALERT_RELATIVE_ZSCORE_TRIGGER:
        return "denominator"
    return "neutral"


def _detect_relative_events(pair_history: pd.DataFrame, *, after_date: str | None) -> list[AlertEvent]:
    history = _normalise_date_column(pair_history)
    required = {"date", "pair_id", "zscore"}
    if history.empty or not required.issubset(history.columns):
        return []
    core = set(ALERT_CORE_EXPOSURES)
    pair_specs = {
        str(pair["pair_id"]): pair
        for pair in RELATIVE_PAIRS
        if (set(pair.get("left", ())) | set(pair.get("right", ()))) <= core
    }
    events: list[AlertEvent] = []
    for pair_id, group in history.groupby("pair_id", sort=False):
        pair = pair_specs.get(str(pair_id))
        if pair is None:
            continue
        group = group.sort_values("date").drop_duplicates("date", keep="last")
        states = group["zscore"].map(_pair_zone)
        states.index = group["date"].tolist()
        values = pd.to_numeric(group["zscore"], errors="coerce")
        values.index = states.index
        for event_date, old_state, new_state, value in _confirmed_transitions(
            states,
            values,
            after_date=after_date,
            transition_filter=lambda old, new: new in {"numerator", "denominator"},
        ):
            label = str(pair.get("label_zh") or pair_id)
            value_text = "—" if pd.isna(value) else f"{float(value):+.2f}"
            events.append(
                _event(
                    "relative_extreme",
                    str(pair_id),
                    label,
                    event_date,
                    f"相对强弱 {label}：由 {_ZONE_LABELS_ZH.get(old_state, old_state)} 进入 {_ZONE_LABELS_ZH.get(new_state, new_state)}（z-score {value_text}）。",
                )
            )
    return events


def _operational_events(freshness: Mapping[str, Any] | None, report_date: str) -> list[AlertEvent]:
    events: list[AlertEvent] = []
    for error in (freshness or {}).get("fetch_errors", []) or []:
        if not isinstance(error, Mapping) or error.get("severity") != "event":
            continue
        dataset = str(error.get("dataset") or "data")
        ticker = _normalise_ticker(error.get("ticker")) or dataset
        message = str(error.get("error") or "数据事件")
        # An emitter that knows what it found declares it. Falling back to
        # the dataset name keeps older artifacts and any future event emitter
        # working, but it must not label a registry disagreement as a rate cut.
        declared = str(error.get("event_type") or "").strip()
        if declared:
            event_type = declared
        else:
            event_type = "fee_change" if dataset == "fund_fee" else "data_event"
        prefix = _EVENT_PREFIXES_ZH.get(event_type, "重要数据事件")
        events.append(
            _event(
                event_type,
                ticker,
                ticker,
                report_date,
                f"{prefix}：{message}。",
                # These are observed fresh on every run for as long as they
                # hold, unlike a dated market transition that is detected once.
                recurring_condition=True,
            )
        )
    return events


def _freshness_blockers(
    freshness: Mapping[str, Any] | None,
    *,
    mode: str,
) -> tuple[str, ...]:
    """Mirror the CLI freshness gate for callers that use policy directly.

    In the shipped CLI path this never fires on its own: ``--require-fresh``
    blocks first and reports the degradation to CI. It exists so a direct
    caller of ``evaluate_alert`` is not quietly less safe than the CLI, which
    means the two rules have to stay in step -- in particular both skip
    ``severity="event"`` entries, which are news rather than broken data.
    """
    if not freshness:
        return ()
    records: list[tuple[str, Mapping[str, Any]]] = []
    freshness_keys = ("quote",) if mode == "intraday" else ("quote", "daily_close")
    for key in freshness_keys:
        record = freshness.get(key)
        if isinstance(record, Mapping):
            records.append((key, record))
    for parent_key, prefix in (
        ("daily_close_by_region", "region"),
        ("daily_close_by_source", "source"),
    ):
        grouped = freshness.get(parent_key)
        if not isinstance(grouped, Mapping):
            continue
        for group, record in grouped.items():
            if isinstance(record, Mapping):
                records.append((f"{prefix} {group}", record))

    blockers = [
        f"{scope}: {record.get('status')}"
        for scope, record in records
        if str(record.get("status")) in BLOCKING_FRESHNESS_STATUSES
    ]
    regressions = freshness.get("coverage_regressions") or []
    blockers.extend(f"coverage regression: {item}" for item in regressions[:6])
    for error in freshness.get("fetch_errors", []) or []:
        if isinstance(error, Mapping) and error.get("severity") != "event":
            dataset = str(error.get("dataset") or "data")
            blockers.append(f"fetch error: {dataset}")
    return tuple(blockers)


def _pending_events(state: Mapping[str, Any]) -> list[AlertEvent]:
    events: list[AlertEvent] = []
    for item in state.get("pending_events", []) or []:
        if isinstance(item, Mapping):
            event = AlertEvent.from_mapping(item)
            if event is not None:
                events.append(event)
    return events


def _dedupe_events(events: Sequence[AlertEvent]) -> list[AlertEvent]:
    deduped: dict[str, AlertEvent] = {}
    for event in events:
        deduped.setdefault(event.event_key, event)
    return sorted(
        deduped.values(),
        key=lambda event: (event.observation_date, event.priority, event.event_type, event.entity_id),
    )


def _reason_lines(kind: str, events: Sequence[AlertEvent], total_count: int) -> tuple[str, ...]:
    if kind == "baseline":
        return ("首次启用事件告警：发送一封基线快报，并从本次观察日开始记录变化。",)
    if kind == "weekly":
        if any(event.event_type == "weekly_heartbeat" for event in events):
            return ("上次每周摘要未送达，现重试；本周没有新的已确认重大变化。",)
        return ("本周没有新的已确认重大变化；按每周兜底节奏发送摘要。",)
    if kind == "manual":
        return ("手动要求发送当前快报。",)
    lines = tuple(event.detail for event in events[:ALERT_MAX_EVENTS_IN_EMAIL])
    if total_count > len(lines):
        return (*lines, f"另有 {total_count - len(lines)} 项变化已合并，完整历史仍可在 dashboard 查看。")
    return lines


def evaluate_alert(
    *,
    report_date: str,
    mode: str,
    state: Mapping[str, Any] | None,
    technicals: pd.DataFrame,
    index_prices: pd.DataFrame,
    wrappers: pd.DataFrame,
    premium_history: pd.DataFrame,
    relative_pair_history: pd.DataFrame,
    freshness: Mapping[str, Any] | None = None,
    force: bool = False,
) -> AlertDecision:
    """Evaluate whether this run should send a report."""
    del technicals  # Latest snapshot is rendered; history is rebuilt from prices.
    normalised_state = _normalise_state(state or {})
    premium = _premium_history_with_current(premium_history, wrappers, report_date=report_date)
    observation_date = _latest_observation_date(index_prices, premium, relative_pair_history)
    cursor = (normalised_state.get("last_evaluated_by_mode") or {}).get(mode)
    pending_events = _pending_events(normalised_state)

    if force:
        events = _dedupe_events(
            [
                *pending_events,
                *_operational_events(freshness, report_date),
            ]
        )
        return AlertDecision(
            should_send=True,
            kind="manual",
            report_date=report_date,
            observation_date=observation_date,
            events=tuple(events[:ALERT_STATE_MAX_EVENT_KEYS]),
            reason_lines=_reason_lines("manual", events, len(events)),
            total_event_count=len(events),
        )

    freshness_blockers = _freshness_blockers(freshness, mode=mode)
    if freshness_blockers:
        # Do not return an observation cursor here.  A blocked run must not
        # advance past an event that a later healthy run still needs to see.
        return AlertDecision(
            should_send=False,
            kind="none",
            report_date=report_date,
            observation_date=None,
            reason_lines=(
                "数据未通过 freshness gate，暂不发送告警："
                + "；".join(freshness_blockers[:6]),
            ),
        )

    if not normalised_state["baseline_initialized"]:
        if observation_date is None:
            return AlertDecision(
                should_send=False,
                kind="none",
                report_date=report_date,
                observation_date=None,
                reason_lines=("没有可用观察数据，暂不建立告警基线。",),
            )
        return AlertDecision(
            should_send=True,
            kind="baseline",
            report_date=report_date,
            observation_date=observation_date,
            reason_lines=_reason_lines("baseline", (), 0),
        )

    # A manually repaired/older state file may say that a baseline exists but
    # have no mode cursor. Treat the current snapshot as that cursor instead
    # of replaying every historical threshold crossing in the repository.
    if cursor is None and observation_date is not None:
        cursor = observation_date

    detected_events = [
        *_detect_entry_status_events(premium, wrappers, after_date=cursor),
        *_detect_leader_events(premium, wrappers, after_date=cursor),
        *_detect_technical_events(index_prices, after_date=cursor),
        *_detect_relative_events(relative_pair_history, after_date=cursor),
        *_operational_events(freshness, report_date),
    ]
    sent_event_keys = set(normalised_state.get("sent_event_keys") or [])
    events = _dedupe_events(
        [
            *pending_events,
            *(event for event in detected_events if event.event_key not in sent_event_keys),
        ]
    )
    if events and all(event.event_type == "weekly_heartbeat" for event in events):
        # A weekly heartbeat is a delivery obligation, not a market event. If
        # SMTP failed, retry it on the next run even when that run is no longer
        # Friday (and even if another email happened earlier that day).
        return AlertDecision(
            should_send=True,
            kind="weekly",
            report_date=report_date,
            observation_date=observation_date,
            events=tuple(events[:ALERT_STATE_MAX_EVENT_KEYS]),
            reason_lines=_reason_lines("weekly", events, 0),
            total_event_count=0,
        )
    if events and normalised_state.get("last_sent_report_date") == report_date:
        return AlertDecision(
            should_send=False,
            kind="deduped",
            report_date=report_date,
            observation_date=observation_date,
            events=tuple(events[:ALERT_STATE_MAX_EVENT_KEYS]),
            reason_lines=("本地已记录今天发送过告警，后续运行不重复发送。",),
            total_event_count=len(events),
        )
    if events:
        return AlertDecision(
            should_send=True,
            kind="event",
            report_date=report_date,
            observation_date=observation_date,
            events=tuple(events[:ALERT_STATE_MAX_EVENT_KEYS]),
            reason_lines=_reason_lines("event", events, len(events)),
            total_event_count=len(events),
        )

    week_key = date.fromisoformat(report_date).strftime("%G-W%V")
    heartbeat_due = (
        date.fromisoformat(report_date).strftime("%A") == ALERT_HEARTBEAT_WEEKDAY
        and normalised_state.get("last_sent_week") != week_key
    )
    if heartbeat_due:
        heartbeat_event = _event(
            "weekly_heartbeat",
            week_key,
            "每周摘要",
            report_date,
            "本周没有新的已确认重大变化；按每周兜底节奏发送摘要。",
        )
        return AlertDecision(
            should_send=True,
            kind="weekly",
            report_date=report_date,
            observation_date=observation_date,
            events=(heartbeat_event,),
            reason_lines=_reason_lines("weekly", (), 0),
            total_event_count=0,
        )
    return AlertDecision(
        should_send=False,
        kind="none",
        report_date=report_date,
        observation_date=observation_date,
        reason_lines=("没有新的已确认重大变化，本次不发送邮件。",),
    )


def state_with_pending_events(
    state: Mapping[str, Any],
    events: Sequence[AlertEvent],
) -> dict[str, Any]:
    """Record events before SMTP so a failed send can be retried next run."""
    updated = _normalise_state(deepcopy(dict(state)))
    deduped = _dedupe_events(events)
    updated["pending_events"] = [event.as_dict() for event in deduped[:ALERT_STATE_MAX_EVENT_KEYS]]
    return updated


def advance_alert_state(
    state: Mapping[str, Any],
    *,
    mode: str,
    observation_date: str | None,
    report_date: str,
    kind: str,
    sent: bool,
    sent_events: Sequence[AlertEvent] = (),
) -> dict[str, Any]:
    """Advance cursors after evaluation, or mark a successfully sent email."""
    updated = _normalise_state(deepcopy(dict(state)))
    if mode not in {"close", "intraday"}:
        raise ValueError(f"unsupported alert mode: {mode}")
    if observation_date:
        modes = ("close", "intraday") if kind == "baseline" else (mode,)
        for cursor_mode in modes:
            current = updated["last_evaluated_by_mode"].get(cursor_mode)
            if current is None or observation_date > current:
                updated["last_evaluated_by_mode"][cursor_mode] = observation_date
        updated["baseline_initialized"] = True
    if sent:
        updated["last_sent_report_date"] = report_date
        updated["last_sent_week"] = date.fromisoformat(report_date).strftime("%G-W%V")
        updated["last_sent_kind"] = kind
        updated["pending_events"] = []
        sent_keys = list(updated.get("sent_event_keys") or [])
        known_keys = set(sent_keys)
        for event in sent_events:
            if event.event_key not in known_keys:
                sent_keys.append(event.event_key)
                known_keys.add(event.event_key)
        updated["sent_event_keys"] = sent_keys[-ALERT_STATE_MAX_EVENT_KEYS:]
    return updated
