"""Threshold, persistence and regime-state logic for the market radar.

States are computed from complete daily histories so a later run can replay
the same sequence. Persistence is counted in consecutive valid observation
dates, not calendar days, so weekends do not create false exits.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .config import (
    BRENT_ENTER,
    CHANGE_DAYS,
    CONFIRM_DAYS,
    EXIT_DAYS,
    HIKE_ENTER,
    HIKE_ESCALATE,
    HIKE_EXIT,
    OIL_PERSISTENT_COUNT,
    OIL_PERSISTENT_WINDOW,
    MAX_CONDITION_GAP_DAYS,
    STATE_SEVERITY,
    SYNC_ZSCORE,
    US10Y_ENTER,
    ZSCORE_MIN_PERIODS,
    ZSCORE_WINDOW,
)


def _sorted(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return (
        out.dropna(subset=["date", "value"])
        .sort_values("date", kind="mergesort")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )


def rolling_zscore(series: pd.Series, window: int = ZSCORE_WINDOW, min_periods: int = ZSCORE_MIN_PERIODS) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std(ddof=0)
    z = (series - mean) / std.replace(0, pd.NA)
    return z.astype("float64")


def consecutive_true(flags: pd.Series) -> pd.Series:
    """Count consecutive True values, resetting on False or NA."""
    groups = flags.ne(True).cumsum()
    counts = flags.eq(True).groupby(groups).cumsum()
    return counts.where(flags.eq(True), 0).astype(int)


def classify_level_states(
    history: pd.DataFrame,
    *,
    enter: float,
    exit: float,
    direction: str = "above",
    confirm_days: int = CONFIRM_DAYS,
    exit_days: int = EXIT_DAYS,
    escalate: float | None = None,
    persistent_window: int | None = None,
    persistent_count: int | None = None,
    reset_on: str | None = None,
) -> pd.DataFrame:
    """Walk a level history into Normal / Watch / Confirmed / Escalating / Improving.

    Watch is a first breach. Confirmed requires ``confirm_days`` consecutive
    breaches. Escalating is a higher threshold after confirmation. Improving
    is a confirmed/escalating episode that has fallen back through the enter
    threshold but has not yet stayed below the exit threshold long enough to
    return to Normal. Persistence is observation-date consecutive, not calendar.
    """
    frame = _sorted(history)
    if frame.empty:
        return frame.assign(
            breached=pd.Series(dtype=bool),
            consecutive_breach=pd.Series(dtype=int),
            consecutive_clear=pd.Series(dtype=int),
            state=pd.Series(dtype=str),
        )
    # A contract/window/target change or a long source outage starts a new
    # persistence episode. Weekends and ordinary holidays remain consecutive,
    # while observations separated by more than a week cannot confirm each
    # other.
    boundary = frame["date"].diff().dt.days.gt(MAX_CONDITION_GAP_DAYS)
    if reset_on and reset_on in frame.columns:
        boundary |= frame[reset_on].astype(str).ne(
            frame[reset_on].astype(str).shift()
        )
    episode = boundary.fillna(True).cumsum()
    frame = frame.copy()
    frame["_episode"] = episode
    parts = [
        _classify_level_episode(
            group.drop(columns="_episode"),
            enter=enter,
            exit=exit,
            direction=direction,
            confirm_days=confirm_days,
            exit_days=exit_days,
            escalate=escalate,
            persistent_window=persistent_window,
            persistent_count=persistent_count,
        )
        for _, group in frame.groupby("_episode", sort=False)
    ]
    return pd.concat(parts, ignore_index=True) if parts else frame.drop(columns="_episode")


def _classify_level_episode(
    frame: pd.DataFrame,
    *,
    enter: float,
    exit: float,
    direction: str,
    confirm_days: int,
    exit_days: int,
    escalate: float | None,
    persistent_window: int | None,
    persistent_count: int | None,
) -> pd.DataFrame:
    frame = frame.reset_index(drop=True)
    values = frame["value"]
    if direction == "above":
        breached = values > enter
        cleared = values < exit
        escalate_flag = values > escalate if escalate is not None else pd.Series(False, index=frame.index)
    else:
        breached = values < enter
        cleared = values > exit
        escalate_flag = values < escalate if escalate is not None else pd.Series(False, index=frame.index)
    consecutive_breach = consecutive_true(breached)
    consecutive_clear = consecutive_true(cleared)
    if persistent_window and persistent_count:
        persistent = breached.rolling(persistent_window, min_periods=persistent_count).sum() >= persistent_count
    else:
        persistent = pd.Series(False, index=frame.index)

    states: list[str] = []
    current = "Normal"
    for idx in frame.index:
        if current in {"Normal", "Watch"}:
            if bool(persistent.iloc[idx]) or int(consecutive_breach.iloc[idx]) >= confirm_days:
                current = "Escalating" if bool(escalate_flag.iloc[idx]) else "Confirmed"
            elif bool(breached.iloc[idx]):
                current = "Watch"
            else:
                current = "Normal"
        elif current in {"Confirmed", "Escalating"}:
            if int(consecutive_clear.iloc[idx]) >= exit_days:
                current = "Normal"
            elif bool(cleared.iloc[idx]):
                current = "Improving"
            elif bool(escalate_flag.iloc[idx]):
                current = "Escalating"
            else:
                current = "Confirmed"
        elif current == "Improving":
            if int(consecutive_clear.iloc[idx]) >= exit_days:
                current = "Normal"
            elif bool(breached.iloc[idx]):
                if bool(escalate_flag.iloc[idx]) or int(consecutive_breach.iloc[idx]) >= confirm_days:
                    current = "Escalating" if bool(escalate_flag.iloc[idx]) else "Confirmed"
                else:
                    current = "Watch"
            else:
                current = "Improving"
        states.append(current)

    frame = frame.copy()
    frame["breached"] = breached.astype(bool)
    frame["consecutive_breach"] = consecutive_breach
    frame["consecutive_clear"] = consecutive_clear
    frame["state"] = states
    return frame


def classify_sync_stress(credit: pd.DataFrame, vix: pd.DataFrame) -> pd.DataFrame:
    """Credit and VIX must move on a shared observation date.

    A 5-day change and 20-day z-score are both required to be positive / above
    the configured z threshold. Missing either series on a date is not a
    confirmation; it is simply no observation.
    """
    left = _sorted(credit).rename(columns={"value": "hy_oas"})[["date", "hy_oas"]]
    right = _sorted(vix).rename(columns={"value": "vix"})[["date", "vix"]]
    merged = left.merge(right, on="date", how="inner")
    if merged.empty:
        return merged.assign(
            hy_change_5d=pd.Series(dtype=float),
            vix_change_5d=pd.Series(dtype=float),
            hy_z=pd.Series(dtype=float),
            vix_z=pd.Series(dtype=float),
            breached=pd.Series(dtype=bool),
            consecutive_breach=pd.Series(dtype=int),
            consecutive_clear=pd.Series(dtype=int),
            state=pd.Series(dtype=str),
        )
    merged["hy_change_5d"] = merged["hy_oas"] - merged["hy_oas"].shift(CHANGE_DAYS)
    merged["vix_change_5d"] = merged["vix"] - merged["vix"].shift(CHANGE_DAYS)
    merged["hy_z"] = rolling_zscore(merged["hy_oas"])
    merged["vix_z"] = rolling_zscore(merged["vix"])
    both_rising = (merged["hy_change_5d"] > 0) & (merged["vix_change_5d"] > 0)
    both_elevated = (merged["hy_z"] > SYNC_ZSCORE) & (merged["vix_z"] > SYNC_ZSCORE)
    ready = merged[["hy_change_5d", "vix_change_5d", "hy_z", "vix_z"]].notna().all(axis=1)
    breached = ready & both_rising & both_elevated
    cleared = ready & ~breached
    episode = merged["date"].diff().dt.days.gt(MAX_CONDITION_GAP_DAYS).cumsum()
    merged["breached"] = breached
    merged["consecutive_breach"] = (
        breached.groupby(episode, sort=False)
        .transform(consecutive_true)
        .astype(int)
    )
    merged["consecutive_clear"] = (
        cleared.groupby(episode, sort=False)
        .transform(consecutive_true)
        .astype(int)
    )
    states: list[str] = []
    current = "Normal"
    previous_episode: int | None = None
    for idx in merged.index:
        current_episode = int(episode.iloc[idx])
        if previous_episode is not None and current_episode != previous_episode:
            current = "Normal"
        previous_episode = current_episode
        if not bool(ready.iloc[idx]):
            states.append(current)
            continue
        if current in {"Normal", "Watch"}:
            if int(merged.loc[idx, "consecutive_breach"]) >= CONFIRM_DAYS:
                current = "Confirmed"
            elif bool(breached.iloc[idx]):
                current = "Watch"
            else:
                current = "Normal"
        elif current in {"Confirmed", "Escalating"}:
            if int(merged.loc[idx, "consecutive_clear"]) >= EXIT_DAYS:
                current = "Normal"
            elif bool(cleared.iloc[idx]):
                current = "Improving"
            else:
                current = "Confirmed"
        elif current == "Improving":
            if int(merged.loc[idx, "consecutive_clear"]) >= EXIT_DAYS:
                current = "Normal"
            elif bool(breached.iloc[idx]):
                current = "Confirmed" if int(merged.loc[idx, "consecutive_breach"]) >= CONFIRM_DAYS else "Watch"
            else:
                current = "Improving"
        states.append(current)
    merged["state"] = states
    merged["value"] = merged[["hy_z", "vix_z"]].min(axis=1)
    return merged


def latest_state_row(history: pd.DataFrame) -> dict[str, Any] | None:
    if history is None or history.empty:
        return None
    row = history.iloc[-1]
    payload = {str(k): (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
    date = payload.get("date")
    if hasattr(date, "strftime"):
        payload["date"] = date.strftime("%Y-%m-%d")
    return payload


def overall_state(states: dict[str, str]) -> str:
    if not states:
        return "Normal"
    return max(states.values(), key=lambda name: STATE_SEVERITY.get(name, 0))


def build_indicator_states(
    *,
    brent: pd.DataFrame,
    us10y: pd.DataFrame,
    hike: pd.DataFrame,
    hy_oas: pd.DataFrame,
    vix: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    return {
        "brent": classify_level_states(
            brent,
            enter=BRENT_ENTER,
            exit=BRENT_ENTER,
            persistent_window=OIL_PERSISTENT_WINDOW,
            persistent_count=OIL_PERSISTENT_COUNT,
        ),
        "us10y": classify_level_states(us10y, enter=US10Y_ENTER, exit=US10Y_ENTER),
        "hike_prob": classify_level_states(
            hike,
            enter=HIKE_ENTER,
            exit=HIKE_EXIT,
            escalate=HIKE_ESCALATE,
            reset_on="window_key" if hike is not None and "window_key" in hike.columns else None,
        ),
        "credit_vix": classify_sync_stress(hy_oas, vix),
    }
