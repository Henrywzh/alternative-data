"""Pure transforms for the decision-first Global Market Regime surface."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from .config import (
    CONDITION_RULES,
    DOMAIN_RULES,
    FRESH_CONDITION_STATUSES,
    STATE_SEVERITY,
)
from .pipeline import fresh_state_map
from .signals import overall_state

STATE_LABELS_ZH = {
    "Normal": "正常",
    "Watch": "观察",
    "Confirmed": "确认",
    "Escalating": "升级",
    "Improving": "缓和",
    "Unavailable": "不可用",
}


def _numeric(value: Any) -> float | None:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(number) else float(number)


def _clean_price_history(prices: pd.DataFrame) -> pd.DataFrame:
    if prices is None or prices.empty:
        return pd.DataFrame()
    frame = prices.copy()
    required = {"date", "exposure_id", "close"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return (
        frame.dropna(subset=["date", "exposure_id", "close"])
        .loc[lambda value: value["close"].gt(0)]
        .sort_values(["exposure_id", "date"], kind="mergesort")
        .drop_duplicates(["exposure_id", "date"], keep="last")
        .reset_index(drop=True)
    )


def _distance(indicator_id: str, value: Any, threshold: float) -> float | None:
    number = _numeric(value)
    if number is None:
        return None
    distance = number - float(threshold)
    if CONDITION_RULES[indicator_id]["distance_unit"] == "bp":
        distance *= 100.0
    return round(distance, 6)


def build_threshold_monitor(
    latest: pd.DataFrame,
    condition_states: pd.DataFrame | None = None,
    *,
    fomc_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Attach declared thresholds and persistence progress to latest states."""
    if latest is None or latest.empty:
        return pd.DataFrame()
    history = condition_states.copy() if condition_states is not None else pd.DataFrame()
    if not history.empty:
        history["date"] = pd.to_datetime(history["date"], errors="coerce")
        history = history.dropna(subset=["date"]).sort_values(["indicator_id", "date"])

    rows: list[dict[str, Any]] = []
    for row in latest.to_dict("records"):
        indicator_id = str(row.get("indicator_id") or "")
        rule = CONDITION_RULES.get(indicator_id)
        if rule is None:
            continue
        threshold = _numeric(rule.get("threshold"))
        confirmation_required = int(_numeric(rule.get("confirmation_required")) or 0)
        persistence_window = _numeric(rule.get("persistence_window"))
        if threshold is None or confirmation_required <= 0:
            continue
        item = dict(row)
        item.update(
            {
                "threshold": threshold,
                "domain_id": rule.get("domain_id"),
                "value_unit": rule["value_unit"],
                "distance_unit": rule["distance_unit"],
                "distance": _distance(indicator_id, row.get("value"), threshold),
                "confirmation_required": confirmation_required,
                "rule_en": rule["rule_en"],
                "rule_zh": rule["rule_zh"],
                "persistence_window": rule.get("persistence_window"),
                "persistence_required": rule.get("persistence_required"),
            }
        )
        progress = int(_numeric(row.get("consecutive_breach")) or 0)
        item["confirmation_progress"] = min(progress, confirmation_required)
        item["persistence_count"] = None
        if persistence_window and not history.empty:
            subset = history[history["indicator_id"].astype(str).eq(indicator_id)].tail(
                int(persistence_window)
            )
            if "breached" in subset.columns and not subset.empty:
                item["persistence_count"] = int(subset["breached"].fillna(False).astype(bool).sum())
        item["change_1obs_pp"] = None
        item["change_7d_pp"] = None
        if indicator_id == "fomc_hike" and fomc_history is not None and not fomc_history.empty:
            probability = fomc_history[["date", "hike_prob"]].copy()
            probability["date"] = pd.to_datetime(probability["date"], errors="coerce")
            probability["hike_prob"] = pd.to_numeric(
                probability["hike_prob"], errors="coerce"
            )
            probability = probability.dropna().sort_values("date")
            if len(probability) >= 2:
                item["change_1obs_pp"] = round(
                    float(probability.iloc[-1]["hike_prob"])
                    - float(probability.iloc[-2]["hike_prob"]),
                    6,
                )
                cutoff = probability.iloc[-1]["date"] - pd.Timedelta(days=7)
                weekly_base = probability[probability["date"] <= cutoff]
                if not weekly_base.empty:
                    item["change_7d_pp"] = round(
                        float(probability.iloc[-1]["hike_prob"])
                        - float(weekly_base.iloc[-1]["hike_prob"]),
                        6,
                    )
        rows.append(item)
    return pd.DataFrame(rows)


def build_domain_summary(monitor: pd.DataFrame) -> pd.DataFrame:
    """Aggregate fresh condition states into transparent risk domains."""
    rows: list[dict[str, Any]] = []
    source = monitor.copy() if monitor is not None else pd.DataFrame()
    for domain_id, rule in DOMAIN_RULES.items():
        indicator_ids = {str(value) for value in rule["indicator_ids"]}
        if source.empty or not {"indicator_id", "state", "freshness"}.issubset(source.columns):
            usable = pd.DataFrame()
        else:
            usable = source[
                source["indicator_id"].astype(str).isin(indicator_ids)
                & source["freshness"].isin(FRESH_CONDITION_STATUSES)
                & source["state"].ne("Unavailable")
            ].copy()
        if usable.empty:
            state = "Unavailable"
            active_ids: list[str] = []
        else:
            state = max(
                usable["state"].astype(str),
                key=lambda value: STATE_SEVERITY.get(value, 0),
            )
            active_ids = usable.loc[
                ~usable["state"].isin(["Normal"]),
                "indicator_id",
            ].astype(str).tolist()
        rows.append(
            {
                "domain_id": domain_id,
                "label_en": rule["label_en"],
                "label_zh": rule["label_zh"],
                "state": state,
                "available_indicator_count": int(len(usable)),
                "expected_indicator_count": int(len(indicator_ids)),
                "active_indicator_count": int(len(active_ids)),
                "active_indicator_ids": active_ids,
            }
        )
    return pd.DataFrame(rows)


def build_state_transitions(condition_states: pd.DataFrame) -> pd.DataFrame:
    """Return true state changes, excluding each indicator's initial row."""
    if condition_states is None or condition_states.empty:
        return pd.DataFrame()
    required = {"date", "indicator_id", "state"}
    if not required.issubset(condition_states.columns):
        return pd.DataFrame()
    frame = condition_states.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = (
        frame.dropna(subset=["date", "indicator_id", "state"])
        .sort_values(["indicator_id", "date"], kind="mergesort")
        .drop_duplicates(["indicator_id", "date"], keep="last")
    )
    frame["prior_state"] = frame.groupby("indicator_id", sort=False)["state"].shift(1)
    changed = frame["prior_state"].notna() & frame["state"].ne(frame["prior_state"])
    return frame.loc[changed].sort_values("date").reset_index(drop=True)


def build_regime_summary(
    monitor: pd.DataFrame,
    *,
    alert_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a transparent current-state explanation from fresh conditions."""
    required = {"indicator_id", "state", "freshness"}
    if (
        monitor is None
        or monitor.empty
        or not required.issubset(monitor.columns)
    ):
        return {
            "overall_state": "Unavailable",
            "active_driver_count": 0,
            "active_domain_count": 0,
            "confirmed_domain_count": 0,
            "total_domain_count": len(DOMAIN_RULES),
            "breadth_id": "unavailable",
            "breadth_en": "Unavailable",
            "breadth_zh": "不可用",
            "active_domain_ids": [],
            "defensive_alert_eligible": False,
            "fresh_indicator_count": 0,
            "alert_eligible": False,
            "primary_driver_ids": [],
            "explanation_en": "No valid current regime observations are available.",
            "explanation_zh": "目前没有有效的市场状态观察值。",
            "observation_start": None,
            "observation_end": None,
            "last_sent_at": (alert_state or {}).get("last_sent_at"),
        }
    states = fresh_state_map(monitor)
    aggregate = overall_state(states)
    fresh = monitor[
        monitor["freshness"].isin(FRESH_CONDITION_STATUSES)
        & monitor["state"].ne("Unavailable")
    ].copy()
    if fresh.empty:
        return {
            "overall_state": "Unavailable",
            "active_driver_count": 0,
            "active_domain_count": 0,
            "confirmed_domain_count": 0,
            "total_domain_count": len(DOMAIN_RULES),
            "breadth_id": "unavailable",
            "breadth_en": "Unavailable",
            "breadth_zh": "不可用",
            "defensive_alert_eligible": False,
            "fresh_indicator_count": 0,
            "alert_eligible": False,
            "primary_driver_ids": [],
            "explanation_en": "No fresh regime inputs are available; the last observations remain visible for audit.",
            "explanation_zh": "目前没有新鲜的市场状态输入；最后观察值仅保留供核查。",
            "observation_start": None,
            "observation_end": None,
            "last_sent_at": (alert_state or {}).get("last_sent_at"),
        }
    active = fresh[~fresh["state"].isin(["Normal"])]
    domains = build_domain_summary(monitor)
    active_domains = domains[
        ~domains["state"].isin(["Normal", "Unavailable"])
    ].copy()
    confirmed_domains = domains[
        domains["state"].map(lambda value: STATE_SEVERITY.get(str(value), 0)).ge(
            STATE_SEVERITY["Confirmed"]
        )
    ].copy()
    active_domain_count = int(len(active_domains))
    if active_domain_count == 0:
        breadth_id, breadth_en, breadth_zh = "none", "No spread", "未扩散"
    elif active_domain_count == 1:
        breadth_id, breadth_en, breadth_zh = "narrow", "Narrow", "单一领域"
    elif active_domain_count == 2:
        breadth_id, breadth_en, breadth_zh = "broadening", "Broadening", "正在扩散"
    else:
        breadth_id, breadth_en, breadth_zh = "broad_stress", "Broad stress", "广泛压力"
    financial_state = str(
        domains.loc[
            domains["domain_id"].eq("financial_stress"),
            "state",
        ].iloc[0]
    )
    defensive_alert_eligible = bool(
        len(confirmed_domains) >= 2
        or STATE_SEVERITY.get(financial_state, 0) >= STATE_SEVERITY["Confirmed"]
    )
    max_severity = STATE_SEVERITY.get(aggregate, 0)
    leaders = fresh[
        fresh["state"].map(lambda value: STATE_SEVERITY.get(str(value), 0)).eq(max_severity)
    ]
    if aggregate == "Normal":
        leaders = leaders.iloc[0:0]
    leader_ids = leaders["indicator_id"].astype(str).tolist()
    leader_en = leaders.get("label_en", leaders["indicator_id"]).astype(str).tolist()
    leader_zh = leaders.get("label_zh", leaders["indicator_id"]).astype(str).tolist()
    domain_en = active_domains["label_en"].astype(str).tolist()
    domain_zh = active_domains["label_zh"].astype(str).tolist()
    if leader_en:
        other_driver_count = int(len(active) - len(leaders))
        explanation_en = (
            f"{aggregate} because " + ", ".join(leader_en) + " "
            + ("is" if len(leader_en) == 1 else "are")
            + f" {aggregate}. Breadth is {breadth_en.lower()}"
            + (f" across {', '.join(domain_en)}" if domain_en else "")
            + (
                f"; {other_driver_count} other fresh non-normal driver(s)."
                if other_driver_count
                else "."
            )
        )
        explanation_zh = (
            f"当前为{STATE_LABELS_ZH.get(aggregate, aggregate)}，主要因为"
            + "、".join(leader_zh)
            + f"处于{STATE_LABELS_ZH.get(aggregate, aggregate)}；"
            + f"风险扩散范围为{breadth_zh}"
            + (f"（{'、'.join(domain_zh)}）" if domain_zh else "")
            + (
                f"；另有{other_driver_count}个非正常新鲜信号。"
                if other_driver_count
                else "。"
            )
        )
    else:
        explanation_en = "All fresh headline conditions are Normal."
        explanation_zh = "所有新鲜的核心指标目前均为正常。"
    non_unavailable = monitor["state"].ne("Unavailable")
    alert_eligible = bool(
        non_unavailable.any()
        and monitor.loc[non_unavailable, "freshness"].isin(FRESH_CONDITION_STATUSES).all()
    )
    observed = pd.to_datetime(fresh.get("observation_date"), errors="coerce").dropna()
    return {
        "overall_state": aggregate,
        "active_driver_count": int(len(active)),
        "active_domain_count": active_domain_count,
        "confirmed_domain_count": int(len(confirmed_domains)),
        "total_domain_count": len(DOMAIN_RULES),
        "breadth_id": breadth_id,
        "breadth_en": breadth_en,
        "breadth_zh": breadth_zh,
        "active_domain_ids": active_domains["domain_id"].astype(str).tolist(),
        "defensive_alert_eligible": defensive_alert_eligible,
        "fresh_indicator_count": int(len(fresh)),
        "alert_eligible": alert_eligible,
        "primary_driver_ids": leader_ids,
        "explanation_en": explanation_en,
        "explanation_zh": explanation_zh,
        "observation_start": observed.min().strftime("%Y-%m-%d") if not observed.empty else None,
        "observation_end": observed.max().strftime("%Y-%m-%d") if not observed.empty else None,
        "last_sent_at": (alert_state or {}).get("last_sent_at"),
    }


def rebase_price_history(
    prices: pd.DataFrame,
    *,
    exposure_ids: Sequence[str] | None = None,
    start: Any | None = None,
    end: Any | None = None,
) -> pd.DataFrame:
    """Rebase each selected price series to 100 at its first valid observation."""
    if prices is None or prices.empty:
        return pd.DataFrame()
    frame = _clean_price_history(prices)
    if exposure_ids:
        frame = frame[frame["exposure_id"].astype(str).isin([str(item) for item in exposure_ids])]
    if start is not None:
        frame = frame[frame["date"] >= pd.Timestamp(start)]
    if end is not None:
        frame = frame[frame["date"] <= pd.Timestamp(end)]
    frame = frame.sort_values(["exposure_id", "date"])
    if frame.empty:
        return frame.assign(rebased=pd.Series(dtype=float))
    first = frame.groupby("exposure_id", sort=False)["close"].transform("first")
    frame["rebased"] = frame["close"] / first * 100.0
    return frame.reset_index(drop=True)


def build_cross_asset_returns(
    prices: pd.DataFrame,
    *,
    windows: Sequence[int] = (1, 5, 20, 60),
) -> pd.DataFrame:
    """Calculate exact close-to-close returns at each observation window."""
    if prices is None or prices.empty:
        return pd.DataFrame()
    frame = _clean_price_history(prices)
    rows: list[dict[str, Any]] = []
    for exposure_id, group in frame.groupby("exposure_id", sort=False):
        closes = group["close"].reset_index(drop=True)
        latest = float(closes.iloc[-1])
        item: dict[str, Any] = {
            "exposure_id": str(exposure_id),
            "date": group["date"].iloc[-1],
            "close": latest,
        }
        for window in windows:
            item[f"return_{window}d_pct"] = (
                (latest / float(closes.iloc[-window - 1]) - 1.0) * 100.0
                if len(closes) > window
                else None
            )
        rows.append(item)
    return pd.DataFrame(rows)
