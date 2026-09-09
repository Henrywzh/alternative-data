"""Historical diagnostics for regime thresholds and state transitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from .config import CONDITION_RULES, STATE_SEVERITY


DEFAULT_THRESHOLD_CANDIDATES: Mapping[str, Sequence[float]] = {
    "brent": (90.0, 100.0, 110.0),
    "us10y": (4.0, 4.5, 4.82, 5.0),
    "hike_prob": (55.0, 65.0, 75.0),
    "fomc_hike": (55.0, 65.0, 75.0),
}


def _domain_id(indicator_id: str) -> str | None:
    rule = CONDITION_RULES.get(indicator_id)
    return str(rule.get("domain_id")) if rule and rule.get("domain_id") else None


def build_signal_episodes(condition_states: pd.DataFrame) -> pd.DataFrame:
    """Collapse consecutive non-Normal observations into auditable episodes."""
    required = {"date", "indicator_id", "state"}
    if condition_states is None or condition_states.empty or not required.issubset(
        condition_states.columns
    ):
        return pd.DataFrame()
    frame = condition_states.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = (
        frame.dropna(subset=["date", "indicator_id", "state"])
        .sort_values(["indicator_id", "date"])
        .drop_duplicates(["indicator_id", "date"], keep="last")
    )
    rows: list[dict[str, Any]] = []
    for indicator_id, group in frame.groupby("indicator_id", sort=False):
        episode: dict[str, Any] | None = None
        episode_number = 0
        prior_date: pd.Timestamp | None = None
        for row in group.itertuples(index=False):
            state = str(row.state)
            active = state not in {"Normal", "Unavailable"}
            gap_break = (
                episode is not None
                and prior_date is not None
                and (pd.Timestamp(row.date) - prior_date).days > 7
            )
            if gap_break:
                episode["open_episode"] = False
                rows.append(episode)
                episode = None
            if active and episode is None:
                episode_number += 1
                episode = {
                    "episode_id": f"{indicator_id}-{episode_number:03d}",
                    "indicator_id": str(indicator_id),
                    "domain_id": _domain_id(str(indicator_id)),
                    "start_date": row.date,
                    "end_date": row.date,
                    "observation_count": 1,
                    "entry_state": state,
                    "max_state": state,
                    "open_episode": True,
                }
            elif active and episode is not None:
                episode["end_date"] = row.date
                episode["observation_count"] += 1
                if STATE_SEVERITY.get(state, 0) > STATE_SEVERITY.get(
                    str(episode["max_state"]), 0
                ):
                    episode["max_state"] = state
            elif not active and episode is not None:
                episode["open_episode"] = False
                rows.append(episode)
                episode = None
            prior_date = pd.Timestamp(row.date)
        if episode is not None:
            rows.append(episode)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["duration_calendar_days"] = (
        result["end_date"] - result["start_date"]
    ).dt.days + 1
    return result.sort_values(["start_date", "indicator_id"]).reset_index(drop=True)


def build_threshold_sensitivity(
    condition_states: pd.DataFrame,
    *,
    candidates: Mapping[str, Sequence[float]] = DEFAULT_THRESHOLD_CANDIDATES,
) -> pd.DataFrame:
    """Count raw threshold hits and distinct hit episodes for calibration."""
    required = {"date", "indicator_id", "value"}
    if condition_states is None or condition_states.empty or not required.issubset(
        condition_states.columns
    ):
        return pd.DataFrame()
    frame = condition_states.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = (
        frame.dropna(subset=["date", "indicator_id", "value"])
        .sort_values(["indicator_id", "date"], kind="mergesort")
        .drop_duplicates(["indicator_id", "date"], keep="last")
    )
    rows: list[dict[str, Any]] = []
    for indicator_id, thresholds in candidates.items():
        history = frame[frame["indicator_id"].astype(str).eq(indicator_id)]
        if history.empty:
            continue
        for threshold in thresholds:
            hit = history["value"].gt(float(threshold))
            long_gap = history["date"].diff().dt.days.gt(7).fillna(False)
            entries = hit & (~hit.shift(1, fill_value=False) | long_gap)
            rows.append(
                {
                    "indicator_id": indicator_id,
                    "domain_id": _domain_id(indicator_id),
                    "threshold": float(threshold),
                    "is_current_threshold": float(threshold)
                    == float(CONDITION_RULES[indicator_id]["threshold"]),
                    "observation_count": int(len(history)),
                    "above_count": int(hit.sum()),
                    "above_share_pct": float(hit.mean() * 100.0),
                    "raw_hit_episode_count": int(entries.sum()),
                    "start_date": history["date"].min(),
                    "end_date": history["date"].max(),
                }
            )
    return pd.DataFrame(rows)


def build_event_forward_returns(
    transitions: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    horizons: Sequence[int] = (5, 20, 60),
) -> pd.DataFrame:
    """Measure returns from each market's first session after a transition.

    A strict next-session origin avoids using an Asian close that occurred
    before a same-calendar-day US macro observation became knowable.
    """
    transition_required = {"date", "indicator_id", "state"}
    price_required = {"date", "exposure_id", "close"}
    if (
        transitions is None
        or transitions.empty
        or not transition_required.issubset(transitions.columns)
        or prices is None
        or prices.empty
        or not price_required.issubset(prices.columns)
    ):
        return pd.DataFrame()
    transitions = transitions.copy()
    transitions["date"] = pd.to_datetime(transitions["date"], errors="coerce")
    transitions = transitions.dropna(subset=["date"]).sort_values(
        ["indicator_id", "date"]
    )
    transitions = transitions.drop_duplicates(
        ["indicator_id", "date"], keep="last"
    )
    episode_entries: list[dict[str, Any]] = []
    confirmed_severity = STATE_SEVERITY["Confirmed"]
    for _, history in transitions.groupby("indicator_id", sort=False):
        emitted_in_episode = False
        previous_date: pd.Timestamp | None = None
        previous_state = "Normal"
        for row in history.to_dict("records"):
            state = str(row.get("state"))
            row_date = pd.Timestamp(row["date"])
            if previous_date is not None and (row_date - previous_date).days > 7:
                emitted_in_episode = False
                previous_state = "Normal"
            if state in {"Normal", "Unavailable"}:
                emitted_in_episode = False
                previous_state = state
                previous_date = row_date
                continue
            if (
                not emitted_in_episode
                and STATE_SEVERITY.get(state, 0) >= confirmed_severity
            ):
                event = dict(row)
                event["prior_state"] = str(
                    row.get("prior_state") or previous_state
                )
                episode_entries.append(event)
                emitted_in_episode = True
            previous_state = state
            previous_date = row_date
    events = pd.DataFrame(episode_entries)
    if events.empty:
        return pd.DataFrame()
    events = events.sort_values(["date", "indicator_id"])
    market = prices.copy()
    market["date"] = pd.to_datetime(market["date"], errors="coerce")
    market["close"] = pd.to_numeric(market["close"], errors="coerce")
    market = (
        market.dropna(subset=["date", "exposure_id", "close"])
        .loc[lambda frame: frame["close"].gt(0)]
        .sort_values(["exposure_id", "date"])
        .drop_duplicates(["exposure_id", "date"], keep="last")
    )
    rows: list[dict[str, Any]] = []
    grouped_prices = {
        str(exposure_id): group.reset_index(drop=True)
        for exposure_id, group in market.groupby("exposure_id", sort=False)
    }
    for event_number, event in enumerate(events.itertuples(index=False), start=1):
        event_date = pd.Timestamp(event.date)
        for exposure_id, history in grouped_prices.items():
            eligible = history.index[history["date"].gt(event_date)]
            if len(eligible) == 0:
                continue
            origin_index = int(eligible[0])
            origin = history.iloc[origin_index]
            for horizon in horizons:
                target_index = origin_index + int(horizon)
                if target_index >= len(history):
                    continue
                target = history.iloc[target_index]
                rows.append(
                    {
                        "event_id": f"{event.indicator_id}-{event_number:03d}",
                        "event_date": event_date,
                        "indicator_id": str(event.indicator_id),
                        "domain_id": _domain_id(str(event.indicator_id)),
                        "prior_state": str(event.prior_state),
                        "state": str(event.state),
                        "exposure_id": exposure_id,
                        "price_date": origin["date"],
                        "forward_date": target["date"],
                        "horizon_sessions": int(horizon),
                        "forward_return_pct": (
                            float(target["close"]) / float(origin["close"]) - 1.0
                        )
                        * 100.0,
                    }
                )
    return pd.DataFrame(rows)


def summarize_event_forward_returns(forward_returns: pd.DataFrame) -> pd.DataFrame:
    """Aggregate event reactions without promoting small samples to headlines."""
    required = {
        "indicator_id",
        "domain_id",
        "state",
        "event_id",
        "exposure_id",
        "horizon_sessions",
        "forward_return_pct",
    }
    if (
        forward_returns is None
        or forward_returns.empty
        or not required.issubset(forward_returns.columns)
    ):
        return pd.DataFrame()
    grouped = forward_returns.groupby(
        ["indicator_id", "domain_id", "state", "exposure_id", "horizon_sessions"],
        dropna=False,
        as_index=False,
    )
    return grouped.agg(
        event_count=("event_id", "nunique"),
        median_forward_return_pct=("forward_return_pct", "median"),
        mean_forward_return_pct=("forward_return_pct", "mean"),
        positive_share_pct=(
            "forward_return_pct",
            lambda values: float(pd.Series(values).gt(0).mean() * 100.0),
        ),
    )
